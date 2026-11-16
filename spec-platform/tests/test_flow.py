"""자동 점검: 프로필 만들기 -> 추천 -> 갭 분석 -> 후기까지 가는 흐름을 가짜 브라우저로 돌려 봄.
가상 활동은 없으므로, 최근 날짜의 모집 글이 든 테스트용 RSS를 넣고 확인함.
실행: python -m pytest -q   (spec-platform 폴더에서)
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Opportunity, SessionLocal
from tests.helpers import dept_id, tag_id
from tests.test_rss import fresh_db_with_rss


def setup_module():
    fresh_db_with_rss()[0].close()


def client_with_profile():
    from app.main import app
    client = TestClient(app)
    # 컴퓨터소프트웨어학과, 관심: 경영, 스펙: SQLD(id=2) + TOEIC(id=6) 650점
    r = client.post("/profile", data={
        "nickname": "테스트", "department_id": dept_id("컴퓨터소프트웨어학과"), "grade": 3, "admission_year": 2024, "gpa": "3.5",
        "tag_ids": [str(tag_id("경영"))], "spec_ids": ["2", "6"], "score_6": "650",
    }, follow_redirects=False)
    assert r.status_code == 303 and "user_id" in r.cookies
    client.cookies.set("user_id", r.cookies["user_id"])
    return client


def test_no_fake_activities():
    db = SessionLocal()
    rows = db.scalars(select(Opportunity)).all()
    assert rows and all(o.source == "rss" and not o.is_sample and o.url.startswith("https://") for o in rows)
    db.close()


def test_pages_without_profile():
    from app.main import app
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/opportunities").status_code == 200
    r = client.get("/me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/profile/new"
    assert client.get("/api/me").status_code == 401


def test_full_flow():
    client = client_with_profile()
    assert "우리 학교 프로그램" in client.get("/me").text
    recs = client.get("/api/recommendations", params={"scope": "교내"}).json()
    assert recs and all(x["scope"] == "교내" and x["source"] == "rss" for x in recs)
    assert client.get("/api/recommendations", params={"scope": "외부"}).json() == []  # 대외활동은 아직 실제 출처 없음

    # 공기업 전산직(id=4): 정보처리기사 필수(없음), TOEIC 700 필수(650 -> 부족)
    gap = client.get("/api/gap/4").json()
    status = {i["spec"]: i["status"] for i in gap["items"]}
    assert status["정보처리기사"] == "없음" and status["TOEIC"] == "부족" and gap["required_rate"] == 0
    # 백엔드 개발자(id=1): 인턴 경험이 없으면 실제 현장실습 모집 공지가 채울 활동으로 나와야 함
    intern = next(i for i in client.get("/api/gap/1").json()["items"] if i["spec"] == "인턴 경험")
    assert any("현장실습" in f["title"] for f in intern["fillers"])
    for job_id in range(1, 6):
        assert client.get(f"/gap/{job_id}").status_code == 200

    rid = recs[0]["id"]
    r = client.post(f"/opportunities/{rid}/reviews", data={"rating": 4, "content": "테스트 후기입니다"}, follow_redirects=False)
    assert r.status_code == 303
    assert "테스트 후기입니다" in client.get(f"/opportunities/{rid}").text


def test_department_links_to_recommendations():
    """학과의 기본 분야 태그가 실제 공지와 이어져 추천에 나오는지 (프로필 -> 학과 -> 추천)"""
    from app.db import Department
    db = SessionLocal()
    depts = db.scalars(select(Department)).all()
    names = {d.name for d in depts}
    assert len(depts) == len(names) >= 30                       # 이름 중복 없이 세종캠퍼스 학과가 모두 들어 있음
    assert {"약학과", "반도체물리학부", "빅데이터사이언스학부", "스마트도시학부"} <= names
    assert all(len(d.tags) >= 2 for d in depts)                  # 모든 학과가 관련 분야 태그를 가짐
    db.close()


def test_outside_fallback_and_empty_guide():
    """관심 분야가 안 겹쳐도 대외활동이 보이고(최근 순), 데이터가 아예 없으면 해결 방법을 안내해야 함"""
    from datetime import date
    from fastapi.testclient import TestClient
    from app import rss_import, seed
    from app.main import app
    seed.run()
    client = TestClient(app)
    r = client.post("/profile", data={"nickname": "외부", "department_id": dept_id("약학과"), "grade": 1, "admission_year": 2026},
                    follow_redirects=False)
    client.cookies.set("user_id", r.cookies["user_id"])
    assert "python -m app.rss_import" in client.get("/me").text  # 대외활동이 0개면 안내

    db = SessionLocal()
    xml = (f'<rss><channel><item><title>시험용 외부 공고</title><link>/bbs/x/9/artclView.do</link>'
           f'<pubDate>{date.today()} 09:00:00.0</pubDate><description>분야 키워드 없음</description></item></channel></rss>')
    rss_import.save_items(db, rss_import.parse_rss(xml, "https://sejong.korea.ac.kr"),
                          {"host": "세종캠퍼스 외부기관공고", "category": "외부기관공고", "scope": "외부"})
    db.close()
    page = client.get("/me").text
    assert "시험용 외부 공고" in page and "최근 순" in page  # 약학과 관심 분야와 안 겹쳐도 최근 대외활동으로 보임


def test_forged_cookie_is_rejected():
    """쿠키 번호를 직접 바꿔도(위조) 로그인되지 않아야 함"""
    from app import security
    from app.main import app
    good = client_with_profile()
    assert good.get("/api/me").status_code == 200
    real = [c.value for c in good.cookies.jar if c.name == "user_id"][0]  # (같은 이름 쿠키가 둘이라 .get() 대신 목록에서 꺼냄)
    uid = int(real.split(".")[0])
    sig = real.split(".")[1]
    for fake in [str(uid), f"{uid}.{'0' * 32}", f"{uid + 1}.{sig}", "abc.def", ""]:
        forged = TestClient(app)  # 새 손님: 쿠키가 하나도 없는 상태에서 위조 값만 넣음
        forged.cookies.set("user_id", fake)
        assert forged.get("/api/me").status_code == 401, fake
    assert security.verify(security.sign(7)) == 7 and security.verify(None) is None


def test_deploy_pieces(tmp_path, monkeypatch):
    """서버 배포용 부품: DB 주소 변환, 빈 DB 자동 채움(있으면 건드리지 않음), healthz"""
    from app import db as dbmod, seed
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db?sslmode=require")
    assert str(dbmod.make_engine().url).startswith("postgresql+psycopg://u:***@host/db")  # 비밀번호는 가려져 나옴
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    assert dbmod.make_engine().url.drivername == "postgresql+psycopg"
    monkeypatch.delenv("DATABASE_URL")
    assert dbmod.make_engine().url.drivername == "sqlite"

    seed.run()
    assert seed.ensure() is False  # 이미 데이터가 있으면 아무것도 하지 않음
    db = SessionLocal()
    before = db.scalar(select(__import__("sqlalchemy").func.count(Opportunity.id)))
    db.close()
    from app.main import app
    assert TestClient(app).get("/healthz").json() == {"ok": True}
    # 완전히 빈 DB에서는 기본 데이터를 채움
    from app.db import Base, engine
    Base.metadata.drop_all(engine)
    assert seed.ensure() is True
    db = SessionLocal()
    from app.db import Department
    assert db.scalar(select(__import__("sqlalchemy").func.count(Department.id))) == 36 and before >= 1
    db.close()


def test_database_url_cleanup():
    """Neon 복사 글자에 명령어·따옴표·줄바꿈이 붙어 있어도 주소만 꺼내야 함 (배포 중 실제로 난 오류 대응)"""
    from app import db as dbmod
    pure = "postgresql://u:p@ep-x.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    for raw in [pure, f"psql '{pure}'", f'"{pure}"', f"  {pure}\n", f"DATABASE_URL={pure}", f"psql '{pure}'\n"]:
        assert dbmod.clean_database_url(raw) == pure, raw
    import os
    os.environ["DATABASE_URL"] = f"psql '{pure}'"
    try:
        assert dbmod.make_engine().url.drivername == "postgresql+psycopg"
        os.environ["DATABASE_URL"] = "엉뚱한 글자"
        try:
            dbmod.make_engine()
            assert False, "잘못된 주소는 오류여야 함"
        except RuntimeError as e:
            assert "엉뚱한" not in str(e)  # 값 자체는 오류 문구에 넣지 않음
    finally:
        os.environ.pop("DATABASE_URL", None)


def test_privacy_delete_and_review_once():
    """개인정보 안내 페이지, 내 정보 삭제, 같은 활동에 후기 한 개만"""
    from app.db import Review, User
    fresh_db_with_rss()[0].close()  # 앞 테스트가 DB를 바꿔 놓았을 수 있어서, 최근 공지가 있는 상태로 다시 준비
    client = client_with_profile()
    assert client.get("/privacy").status_code == 200 and "Neon" in client.get("/privacy").text
    assert 'href="/privacy"' in client.get("/").text

    rid = client.get("/api/recommendations", params={"scope": "교내"}).json()[0]["id"]
    client.post(f"/opportunities/{rid}/reviews", data={"rating": 5, "content": "첫 번째 후기입니다"})
    client.post(f"/opportunities/{rid}/reviews", data={"rating": 2, "content": "고쳐 쓴 후기입니다"})
    page = client.get(f"/opportunities/{rid}").text
    assert "고쳐 쓴 후기입니다" in page and "첫 번째 후기입니다" not in page  # 두 번 써도 하나만 남음

    uid = client.get("/api/me").json()["id"]
    assert client.post("/profile/delete", data={}, follow_redirects=False).status_code == 400  # 확인 체크 없으면 거절
    r = client.post("/profile/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and "deleted=1" in r.headers["location"]
    db = SessionLocal()
    assert db.get(User, uid) is None
    assert db.scalars(select(Review).where(Review.user_id == uid)).first() is None
    db.close()
