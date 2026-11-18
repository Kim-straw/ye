"""로그인(아이디·비밀번호) 점검: 가입·로그인·실패 문구·중복·형식·해시 저장·무차별 대입 막기·마이그레이션·기존 사용자 연결"""
import os
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from app import accounts, seed
from app.db import SessionLocal, User, migrate_users
from app.main import app
from tests.helpers import dept_id


def signup(client, login_id="sejong_1", password="password123", password2=None, nickname="로그인테스트"):
    data = {"nickname": nickname, "department_id": dept_id("약학과"), "grade": 2, "admission_year": 2025,
            "login_id": login_id, "password": password, "password2": password if password2 is None else password2, "agree": "on"}
    return client.post("/profile", data=data, follow_redirects=False)


def cookie_of(resp):
    return resp.cookies.get("user_id")


def setup_function():
    seed.run()
    accounts.limiter._fails.clear()


def test_signup_logout_login():
    c = TestClient(app)
    r = signup(c)
    assert r.status_code == 303 and cookie_of(r)
    # 로그아웃한 것과 같은 상태(쿠키 없는 새 기기)에서 로그인
    other = TestClient(app)
    assert other.get("/me", follow_redirects=False).status_code == 303  # 로그인 전에는 들어갈 수 없음
    ok = other.post("/login", data={"login_id": "SEJONG_1 ", "password": "password123"}, follow_redirects=False)  # 대문자·공백은 정리됨
    assert ok.status_code == 303 and ok.headers["location"] == "/me"
    other.cookies.set("user_id", cookie_of(ok))
    assert "로그인테스트님 추천" in other.get("/me").text


def test_wrong_password_and_unknown_id_give_same_message():
    c = TestClient(app)
    signup(c)
    wrong = c.post("/login", data={"login_id": "sejong_1", "password": "wrongpass1"})
    nobody = c.post("/login", data={"login_id": "no_such_id", "password": "password123"})
    assert wrong.status_code == nobody.status_code == 401
    assert "아이디 또는 비밀번호가 맞지 않아요" in wrong.text and "아이디 또는 비밀번호가 맞지 않아요" in nobody.text
    assert "user_id" not in wrong.cookies


def test_duplicate_and_format_rules():
    c = TestClient(app)
    signup(c)
    dup = signup(TestClient(app), login_id="sejong_1")
    assert dup.status_code == 400 and "이미 쓰는 아이디예요" in dup.text
    assert "로그인테스트" in dup.text  # 실패해도 입력한 닉네임이 남아 있음
    assert "4~20자" in signup(TestClient(app), login_id="ab").text            # 너무 짧음
    assert "4~20자" in signup(TestClient(app), login_id="한글아이디").text      # 허용 안 되는 글자
    assert "8~72자" in signup(TestClient(app), login_id="short_pw", password="1234567").text
    assert "확인이 맞지 않아요" in signup(TestClient(app), login_id="mismatch", password2="password999").text
    db = SessionLocal()
    assert db.scalar(select(User).where(User.login_id == "mismatch")) is None  # 실패하면 사용자를 만들지 않음
    db.close()


def test_password_is_stored_only_as_hash():
    c = TestClient(app)
    r = signup(c, login_id="hash_check", password="my-secret-pw")
    db = SessionLocal()
    u = db.scalars(select(User).where(User.login_id == "hash_check")).one()
    assert u.password_hash.startswith("pbkdf2$") and "my-secret-pw" not in u.password_hash
    assert accounts.verify_password("my-secret-pw", u.password_hash) and not accounts.verify_password("other", u.password_hash)
    # 같은 비밀번호도 salt가 달라 해시가 다름
    assert accounts.hash_password("my-secret-pw") != u.password_hash
    db.close()
    c.cookies.set("user_id", cookie_of(r))
    me = c.get("/api/me").text
    assert "my-secret-pw" not in me and "pbkdf2" not in me and "password" not in me


def test_too_many_failures_are_blocked():
    c = TestClient(app)
    signup(c, login_id="brute_me")
    for _ in range(accounts.LoginLimiter.LIMIT):
        assert c.post("/login", data={"login_id": "brute_me", "password": "guess-guess"}).status_code == 401
    blocked = c.post("/login", data={"login_id": "brute_me", "password": "password123"}, follow_redirects=False)  # 맞는 비밀번호도 잠시 막힘
    assert blocked.status_code == 429 and "잠시 후 다시 시도해 주세요" in blocked.text
    assert c.post("/login", data={"login_id": "other_id", "password": "x" * 8}).status_code == 401  # 다른 아이디는 영향 없음


def test_migration_adds_columns_to_old_db_and_is_repeatable():
    """로그인 칸이 없던 옛 DB에 칸을 추가하고, 두 번 돌려도 오류 없이 기존 사용자가 그대로 남아야 함"""
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, school_id INTEGER, department_id INTEGER, nickname VARCHAR(20), "
                          "grade INTEGER, admission_year INTEGER, gpa FLOAT, mileage INTEGER)"))
        conn.execute(text("INSERT INTO users VALUES (1, 1, 1, '옛사용자', 3, 2024, NULL, 0)"))
    assert migrate_users(eng) == ["login_id", "password_hash"]
    assert migrate_users(eng) == []  # 두 번째는 할 일 없음
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"login_id", "password_hash"} <= cols
    with eng.begin() as conn:
        assert conn.execute(text("SELECT nickname, login_id FROM users WHERE id = 1")).one() == ("옛사용자", None)
        conn.execute(text("UPDATE users SET login_id = 'dup_id' WHERE id = 1"))
        conn.execute(text("INSERT INTO users (id, nickname, login_id) VALUES (2, 'b', NULL), (3, 'c', NULL)"))  # 빈 아이디는 여러 명 가능
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO users (id, nickname, login_id) VALUES (4, 'd', 'dup_id')"))
        raise AssertionError("같은 아이디가 두 번 저장되면 안 됨")
    except Exception as e:
        assert "UNIQUE" in str(e).upper()


def test_cookie_only_user_can_link_login():
    """예전 방식(아이디 없이 쿠키만)으로 만든 사용자가 나중에 로그인 정보를 연결"""
    c = TestClient(app)
    r = c.post("/profile", data={"nickname": "옛방식", "department_id": dept_id("약학과"), "grade": 1, "admission_year": 2026},
               follow_redirects=False)
    c.cookies.set("user_id", cookie_of(r))
    page = c.get("/profile/new").text
    assert "로그인 정보 만들기" in page and "다시 들어올 수 없어요" in page
    bad = c.post("/account", data={"login_id": "old_user", "password": "password123", "password2": "different1"})
    assert bad.status_code == 400 and "확인이 맞지 않아요" in bad.text
    ok = c.post("/account", data={"login_id": "old_user", "password": "password123", "password2": "password123"}, follow_redirects=False)
    assert ok.status_code == 303
    assert "로그인 정보 만들기" not in c.get("/profile/new").text  # 이미 연결됨
    assert c.post("/account", data={"login_id": "again_id", "password": "password123", "password2": "password123"}).status_code == 400
    login = TestClient(app).post("/login", data={"login_id": "old_user", "password": "password123"}, follow_redirects=False)
    assert login.status_code == 303


def test_delete_profile_removes_login():
    c = TestClient(app)
    r = signup(c, login_id="delete_me")
    c.cookies.set("user_id", cookie_of(r))
    c.post("/profile/delete", data={"confirm": "yes"})
    db = SessionLocal()
    assert db.scalar(select(User).where(User.login_id == "delete_me")) is None
    db.close()
    assert TestClient(app).post("/login", data={"login_id": "delete_me", "password": "password123"}).status_code == 401


def test_login_link_and_pages():
    c = TestClient(app)
    home = c.get("/").text
    assert 'href="/login"' in home
    page = c.get("/login").text
    assert "비밀번호를 잊으면 새 프로필을 만들어야 해요" in page and 'method="post"' in page
    assert "로그인 정보" in c.get("/privacy").text
