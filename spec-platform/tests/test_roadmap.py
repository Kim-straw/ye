"""로드맵: 원본 목록 규칙, 학년·분야별 항목, 체크·빼기·직접 넣기, 남의 항목 보호, 삭제 연동, 새 테이블 생성"""
import re

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app import roadmap_data as data
from app import seed
from app.db import RoadmapEntry, SessionLocal, User, engine
from app.main import app
from tests.helpers import dept_id, tag_id


# 예전(학년 구분 없던) 로드맵에서 배포된 원본 항목 key 62개 (2cca32b). 이미 사용자 기록이 붙어 있으므로 사라지면 안 됨
OLD_KEYS = [
    "g1_explore_jobs", "g1_one_activity", "g1_record", "g1_study_habit", "g1_talk_senior", "g2_collect_work",
    "g2_language_plan", "g2_one_tool", "g2_pick_field", "g2_team_project", "g3_check_requirements", "g3_field_experience",
    "g3_narrow_jobs", "g3_portfolio_draft", "g3_resume_draft", "g4_apply_list", "g4_ask_professionals",
    "g4_interview_practice", "g4_polish_resume", "g4_portfolio_final", "t_ai_cases", "t_ai_example", "t_art_collect",
    "t_art_review", "t_bio_lab_note", "t_bio_paper", "t_biz_company", "t_biz_news", "t_counsel_peer",
    "t_counsel_reading", "t_data_chart", "t_data_public", "t_design_portfolio", "t_design_tool", "t_dev_algorithm",
    "t_dev_project", "t_env_issue", "t_env_practice", "t_lang_goal", "t_lang_output", "t_lead_event", "t_lead_role",
    "t_mkt_brand", "t_mkt_content", "t_public_jobs", "t_public_policy", "t_sec_basics", "t_sec_study", "t_semi_jobs",
    "t_semi_process", "t_sport_coach", "t_sport_log", "t_startup_idea", "t_startup_programs", "t_stat_practice",
    "t_stat_read", "t_video_make", "t_video_tool", "t_volunteer_record", "t_volunteer_regular", "t_write_piece",
    "t_write_summary",
]


def all_source_items():
    items = [it for v in data.COMMON.values() for it in v]
    return items + [it for by_grade in data.BY_TAG.values() for v in by_grade.values() for it in v]


def test_source_list_rules():
    keys = [k for k, _ in all_source_items()]
    assert len(keys) == len(set(keys)) == len(data.ALL_ITEMS)           # key가 겹치지 않음
    assert all(re.fullmatch(r"[a-z0-9_]{3,40}", k) for k in keys)       # key는 영문 소문자·숫자·밑줄
    assert all(len(t) <= 40 for t in data.ALL_ITEMS.values())           # 문장은 40자 이내
    assert set(data.COMMON) == {1, 2, 3, 4} and all(4 <= len(v) <= 6 for v in data.COMMON.values())
    assert set(data.BY_TAG) == set(seed.TAGS) == set(data.RESULT_BY_TAG)  # 21개 분야 모두 있음
    for tag in seed.TAGS:                                                 # 분야마다 1~4학년에 항목 정확히 1개, 결과물도 학년마다
        assert set(data.BY_TAG[tag]) == {1, 2, 3, 4} and all(len(v) == 1 for v in data.BY_TAG[tag].values()), tag
        assert set(data.RESULT_BY_TAG[tag]) == {1, 2, 3, 4}, tag
    assert set(data.RESULT_BY_GRADE) == {1, 2, 3, 4}
    assert set(data.KEY_GRADE) == set(data.ALL_ITEMS) and set(data.KEY_GRADE.values()) == {1, 2, 3, 4}
    # 사실처럼 보이는 숫자 정보(점수·날짜·퍼센트)를 넣지 않음
    results = [t for d in data.RESULT_BY_TAG.values() for t in d.values()] + list(data.RESULT_BY_GRADE.values())
    for t in list(data.ALL_ITEMS.values()) + results:
        assert not re.search(r"\d{3,}|\d+\s*(점|월|일|%|년)", t), t
        assert len(t) <= 40, t


def test_old_keys_are_kept():
    """이미 저장된 체크·빼기 기록이 사라져 보이지 않도록, 예전 key는 모두 남아 있어야 함"""
    assert len(OLD_KEYS) == 62 and set(OLD_KEYS) <= set(data.ALL_ITEMS)


# ---------- 화면과 동작 ----------
def make_user(grade=1, dept="반도체물리학부", tags=(), nickname="로드맵"):
    c = TestClient(app)
    data_ = {"nickname": nickname, "department_id": dept_id(dept), "grade": grade, "admission_year": 2025,
             "tag_ids": [tag_id(t) for t in tags]}
    r = c.post("/profile", data=data_, follow_redirects=False)
    c.cookies.set("user_id", r.cookies["user_id"])
    return c


def keys_on(c):
    sec = c.get("/roadmap").text.split("지금 준비할 것")[1].split("이번 학기 결과물")[0]
    return {m.group(1): m.group(2) == "true" for m in re.finditer(r'name="key" value="([^"]+)">\s*<button type="submit" aria-pressed="(true|false)"', sec)}


def progress(c):
    m = re.search(r'class="rm-progress"[^>]*><b>(\d+)</b><span>/ (\d+)</span>', c.get("/roadmap").text)
    return int(m.group(1)), int(m.group(2))


def setup_function():
    seed.run()


def test_items_depend_on_grade_department_and_interests():
    g1 = set(keys_on(make_user(grade=1)))
    g4 = set(keys_on(make_user(grade=4)))
    common1 = {k for k, _ in data.COMMON[1]}
    assert common1 <= g1 and not common1 & g4 and {k for k, _ in data.COMMON[4]} <= g4
    dept_tags = {"반도체", "개발"}  # 반도체물리학부의 기본 분야
    expected_tag_keys = {k for t in dept_tags for k, _ in data.BY_TAG[t][1]}
    assert expected_tag_keys <= g1 and not {k for k, _ in data.BY_TAG["마케팅"][1]} & g1
    with_marketing = set(keys_on(make_user(grade=1, tags=["마케팅"])))
    assert {k for k, _ in data.BY_TAG["마케팅"][1]} <= with_marketing     # 관심 분야를 고르면 그 항목이 추가됨
    g6 = set(keys_on(make_user(grade=6)))
    assert {k for k, _ in data.COMMON[4]} <= g6                         # 5·6학년은 4학년 항목
    page = make_user(grade=1).get("/roadmap").text
    assert data.RESULT_BY_TAG["반도체"][1] in page                       # 결과물: 학과의 가장 앞선 분야 기준


def test_check_hide_restore_and_progress():
    c = make_user()
    done, total = progress(c)
    assert done == 0 and total == len(keys_on(c))
    key = data.COMMON[1][0][0]
    r = c.post("/roadmap/toggle", data={"key": key}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/roadmap#item-{key}"
    assert keys_on(c)[key] is True and progress(c) == (1, total)
    c.post("/roadmap/toggle", data={"key": key})
    assert keys_on(c)[key] is False and progress(c) == (0, total)
    other = data.COMMON[1][1][0]
    c.post("/roadmap/hide", data={"key": other})
    assert other not in keys_on(c) and progress(c) == (0, total - 1)
    assert "뺀 항목 1개 보기" in c.get("/roadmap").text
    c.post("/roadmap/restore", data={"key": other})
    assert other in keys_on(c) and progress(c) == (0, total)
    db = SessionLocal()
    assert db.scalars(select(RoadmapEntry)).all() == []                # 처음 상태로 돌아오면 저장할 줄도 없음
    db.close()


def test_custom_items_limits_and_delete():
    c = make_user()
    base_total = progress(c)[1]
    assert c.post("/roadmap/custom", data={"text": "   매주 영어 단어 외우기  "}, follow_redirects=False).status_code == 303
    customs = [k for k in keys_on(c) if k.startswith("custom:")]
    assert len(customs) == 1 and "매주 영어 단어 외우기" in c.get("/roadmap").text and progress(c) == (0, base_total + 1)
    c.post("/roadmap/toggle", data={"key": customs[0]})
    assert progress(c) == (1, base_total + 1)
    too_long = c.post("/roadmap/custom", data={"text": "가" * 61})
    assert too_long.status_code == 400 and "60자 이내" in too_long.text
    blank = c.post("/roadmap/custom", data={"text": "    "})
    assert blank.status_code == 400 and "적어 주세요" in blank.text
    for i in range(19):
        assert c.post("/roadmap/custom", data={"text": f"항목 {i}"}, follow_redirects=False).status_code == 303
    over = c.post("/roadmap/custom", data={"text": "스물한 번째"})
    assert over.status_code == 400 and "20개까지" in over.text
    c.post("/roadmap/custom/delete", data={"key": customs[0]})
    assert customs[0] not in keys_on(c)
    assert c.post("/roadmap/hide", data={"key": "custom:abc"}).status_code == 404   # 직접 넣은 항목은 빼기 대신 삭제
    assert c.post("/roadmap/toggle", data={"key": "not_a_real_key"}).status_code == 404


def test_cannot_touch_other_users_items():
    alice, bob = make_user(nickname="앨리스"), make_user(nickname="밥")
    alice.post("/roadmap/custom", data={"text": "앨리스의 항목"})
    alice_key = [k for k in keys_on(alice) if k.startswith("custom:")][0]
    assert bob.post("/roadmap/toggle", data={"key": alice_key}).status_code == 404
    assert bob.post("/roadmap/custom/delete", data={"key": alice_key}).status_code == 404
    assert "앨리스의 항목" not in bob.get("/roadmap").text
    assert keys_on(alice)[alice_key] is False                            # 앨리스 것은 그대로
    stranger = TestClient(app)
    assert stranger.get("/roadmap", follow_redirects=False).headers["location"] == "/profile/new"
    assert stranger.post("/roadmap/custom", data={"text": "x"}, follow_redirects=False).status_code == 303


def test_custom_text_is_escaped():
    c = make_user()
    c.post("/roadmap/custom", data={"text": "<script>alert(1)</script>"})
    html = c.get("/roadmap").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_delete_profile_removes_roadmap():
    c = make_user()
    c.post("/roadmap/custom", data={"text": "지워질 항목"})
    c.post("/roadmap/toggle", data={"key": data.COMMON[1][0][0]})
    db = SessionLocal()
    assert len(db.scalars(select(RoadmapEntry)).all()) == 2
    db.close()
    c.post("/profile/delete", data={"confirm": "yes"})
    db = SessionLocal()
    assert db.scalars(select(RoadmapEntry)).all() == []
    db.close()


def test_checks_survive_grade_change():
    c = make_user(grade=1)
    key = data.COMMON[1][0][0]
    c.post("/roadmap/toggle", data={"key": key})
    form = {"nickname": "로드맵", "department_id": dept_id("반도체물리학부"), "admission_year": 2025}
    c.post("/profile", data={**form, "grade": 2})
    assert key not in keys_on(c)                                         # 2학년에는 안 보임
    c.post("/profile", data={**form, "grade": 1})
    assert keys_on(c)[key] is True                                       # 1학년으로 돌아오면 체크가 그대로


def test_me_shows_roadmap_link():
    c = make_user()
    c.post("/roadmap/toggle", data={"key": data.COMMON[1][0][0]})
    done, total = progress(c)
    assert f'href="/roadmap">이번 학기 로드맵 <b>{done}/{total}</b>' in c.get("/me").text


def test_startup_creates_table_on_old_db():
    """로드맵 테이블이 없던 옛 DB로 서버를 켜면 테이블이 생기고 기존 사용자는 그대로 (두 번 켜도 오류 없음)"""
    make_user(nickname="옛사용자")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE roadmap_entries"))
    assert "roadmap_entries" not in inspect(engine).get_table_names()
    seed.ensure()
    seed.ensure()
    assert "roadmap_entries" in inspect(engine).get_table_names()
    db = SessionLocal()
    assert db.scalars(select(User).where(User.nickname == "옛사용자")).first() is not None
    db.close()


def test_privacy_mentions_roadmap():
    page = TestClient(app).get("/privacy").text
    assert "<b>로드맵</b>: 체크하거나 뺀 항목, 직접 넣은 항목" in page and "로드맵 기록이 바로 지워집니다" in page
