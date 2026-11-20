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


ITEM_RE = re.compile(r'name="key" value="([^"]+)">\s*<button type="submit" aria-pressed="(true|false)"')


def sections(c, url="/roadmap"):
    """화면의 학년 구역 4개: {학년: {open, now, keys{key: 체크됨?}, progress(done, total), result}}"""
    html = c.get(url).text
    out = {}
    for m in re.finditer(r'<details class="rm-grade( now)?" id="grade-(\d)"( open)?>(.*?)</details>', html, re.S):
        body = m.group(4)
        cnt = re.search(r'class="rm-sum-count">(\d+) / (\d+)<', body)
        out[int(m.group(2))] = {"now": bool(m.group(1)), "open": bool(m.group(3)),
                                "keys": {k.group(1): k.group(2) == "true" for k in ITEM_RE.finditer(body)},
                                "progress": (int(cnt.group(1)), int(cnt.group(2))),
                                "result": re.search(r'class="rm-result"><span>결과물</span> ([^<]+)</p>', body).group(1)}
    return out


def keys_on(c, grade=None):
    """한 학년 구역(기본: 내 현재 학년)의 항목 {key: 체크됨?}"""
    secs = sections(c)
    g = grade or next(g for g, v in secs.items() if v["now"])
    return secs[g]["keys"]


def progress(c, grade=None):
    secs = sections(c)
    g = grade or next(g for g, v in secs.items() if v["now"])
    return secs[g]["progress"]


def overview(c):
    """한눈에 보기 줄: {학년: (done, total)}"""
    html = c.get("/roadmap").text
    return {int(m.group(1)): (int(m.group(2)), int(m.group(3)))
            for m in re.finditer(r'<span>(\d)학년</span><b>(\d+)<small>/(\d+)</small></b>', html)}


def setup_function():
    seed.run()


def expected_keys(grade, tags):
    return {k for k, _ in data.COMMON[grade]} | {k for t in tags for k, _ in data.BY_TAG[t][grade]}


def test_all_four_grades_for_every_current_grade():
    """핵심: 현재 학년이 1·2·3·4·6학년인 사용자 모두에게 1~4학년 구역 4개가 다 보이고, 학년마다 공통 + 내 분야의 그 학년 항목이 나옴"""
    for dept, tags, chosen in [("반도체물리학부", ["반도체", "개발"], []),
                               ("응용수리과학부 데이터계산과학전공", ["데이터", "AI", "통계"], ["마케팅"])]:
        for current in (1, 2, 3, 4, 6):
            secs = sections(make_user(grade=current, dept=dept, tags=chosen))
            assert sorted(secs) == [1, 2, 3, 4], (dept, current)
            now = min(current, 4)
            assert [g for g, v in secs.items() if v["now"]] == [now]                  # '지금' 표시는 현재 학년 하나 (6학년 -> 4)
            for g in (1, 2, 3, 4):
                assert set(secs[g]["keys"]) == expected_keys(g, tags + chosen), (dept, current, g)
                assert secs[g]["progress"] == (0, len(expected_keys(g, tags + chosen)))
                assert secs[g]["result"] == data.RESULT_BY_TAG[tags[0]][g]           # 학과 대표 분야의 그 학년 결과물


def test_default_open_rule():
    c = make_user(grade=2)
    assert {g for g, v in sections(c).items() if v["open"]} == {2}                   # 기본: 현재 학년만
    assert {g for g, v in sections(c, "/roadmap?open=3").items() if v["open"]} == {2, 3}
    assert {g for g, v in sections(c, "/roadmap?open=all").items() if v["open"]} == {1, 2, 3, 4}
    assert {g for g, v in sections(c, "/roadmap?open=9").items() if v["open"]} == {2}  # 이상한 값은 무시
    assert '<option value="3" selected>' in c.get("/roadmap?open=3").text            # 추가 칸 학년 = 작업 중인 학년
    assert '<option value="2" selected>' in c.get("/roadmap").text                   # 없으면 현재 학년
    page = c.get("/roadmap").text
    assert 'href="/roadmap?open=all">모두 펼치기' in page and 'href="/roadmap">현재 학년만 보기' in c.get("/roadmap?open=all").text
    for g in (1, 2, 3, 4):
        assert f'href="/roadmap?open={g}#grade-{g}"' in page                         # 한눈에 보기 링크가 그 구역을 엶


def test_check_hide_restore_in_every_grade():
    """1학년 사용자가 1~4학년 각 구역에서 체크·해제·빼기·다시 넣기를 하고, 돌아갈 때 그 구역이 열려 있음"""
    c = make_user(grade=1)
    for g in (1, 2, 3, 4):
        keys = list(keys_on(c, g))
        total = len(keys)
        r = c.post("/roadmap/toggle", data={"key": keys[0]}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/roadmap?open={g}#item-{keys[0]}"
        secs = sections(c, r.headers["location"].split("#")[0])
        assert secs[g]["open"] and secs[g]["keys"][keys[0]] is True and secs[g]["progress"] == (1, total)
        assert overview(c)[g] == (1, total)
        c.post("/roadmap/toggle", data={"key": keys[0]})
        assert keys_on(c, g)[keys[0]] is False and progress(c, g) == (0, total)
        r = c.post("/roadmap/hide", data={"key": keys[1]}, follow_redirects=False)
        assert r.headers["location"] == f"/roadmap?open={g}#grade-{g}"
        assert keys[1] not in keys_on(c, g) and progress(c, g) == (0, total - 1)
        assert f"뺀 항목 1개 보기" in c.get("/roadmap").text and f'<span class="rm-tag">{g}학년</span>' in c.get("/roadmap").text
        r = c.post("/roadmap/restore", data={"key": keys[1]}, follow_redirects=False)
        assert r.headers["location"] == f"/roadmap?open={g}#item-{keys[1]}"
        assert keys[1] in keys_on(c, g) and progress(c, g) == (0, total)
    db = SessionLocal()
    assert db.scalars(select(RoadmapEntry)).all() == []                # 처음 상태로 돌아오면 저장할 줄도 없음
    db.close()


def test_custom_items_per_grade_limits_and_delete():
    c = make_user(grade=1)
    base = {g: progress(c, g)[1] for g in (1, 2, 3, 4)}
    for g in (1, 2, 3, 4):
        r = c.post("/roadmap/custom", data={"text": f"  {g}학년에 할 내 항목  ", "grade": str(g)}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith(f"/roadmap?open={g}#item-custom-g{g}-")
        customs = [k for k in keys_on(c, g) if k.startswith("custom:")]
        assert len(customs) == 1 and re.fullmatch(rf"custom:g{g}:[0-9a-f]{{16}}", customs[0]) and len(customs[0]) <= 40
        assert progress(c, g) == (0, base[g] + 1)
        assert all(customs[0] not in keys_on(c, h) for h in (1, 2, 3, 4) if h != g)   # 다른 학년 구역에는 안 나옴
        r = c.post("/roadmap/toggle", data={"key": customs[0]}, follow_redirects=False)
        assert r.headers["location"] == f"/roadmap?open={g}#item-{customs[0].replace(':', '-')}"
        assert progress(c, g) == (1, base[g] + 1)
    key3 = [k for k in keys_on(c, 3) if k.startswith("custom:")][0]
    r = c.post("/roadmap/custom/delete", data={"key": key3}, follow_redirects=False)
    assert r.headers["location"] == "/roadmap?open=3#grade-3" and key3 not in keys_on(c, 3)
    # 오류: 고른 학년 구역이 열린 채로, 입력한 글과 학년이 남음
    too_long = c.post("/roadmap/custom", data={"text": "가" * 61, "grade": "3"})
    assert too_long.status_code == 400 and "60자 이내" in too_long.text
    assert re.search(r'id="grade-3" open', too_long.text) and '<option value="3" selected>' in too_long.text
    assert 'value="' + "가" * 60 + '"' in too_long.text
    blank = c.post("/roadmap/custom", data={"text": "    ", "grade": "2"})
    assert blank.status_code == 400 and "적어 주세요" in blank.text and re.search(r'id="grade-2" open', blank.text)
    for bad in ("0", "5", "x", ""):
        r = c.post("/roadmap/custom", data={"text": "학년이 이상함", "grade": bad})
        assert r.status_code == 400 and "학년을 다시 골라 주세요" in r.text
    for i in range(17):  # 지금 3개 있음(1·2·4학년) -> 합계 20개까지
        assert c.post("/roadmap/custom", data={"text": f"항목 {i}", "grade": str(i % 4 + 1)}, follow_redirects=False).status_code == 303
    over = c.post("/roadmap/custom", data={"text": "스물한 번째", "grade": "4"})
    assert over.status_code == 400 and "20개까지" in over.text and re.search(r'id="grade-4" open', over.text)
    assert c.post("/roadmap/hide", data={"key": "custom:g1:" + "a" * 16}).status_code == 404   # 직접 넣은 항목은 빼기 대신 삭제
    assert c.post("/roadmap/toggle", data={"key": "not_a_real_key"}).status_code == 404


def test_legacy_custom_key_shows_in_current_grade():
    """예전 형식(학년 없는 custom:16자)으로 저장된 항목은 현재 학년 구역에 보이고 체크·삭제가 됨"""
    c = make_user(grade=3, nickname="예전")
    db = SessionLocal()
    uid = db.scalars(select(User.id).where(User.nickname == "예전")).one()
    db.add(RoadmapEntry(user_id=uid, item_key="custom:0123456789abcdef", text="예전에 넣은 항목", done=False, hidden=False))
    db.commit()
    db.close()
    assert "custom:0123456789abcdef" in keys_on(c, 3) and all("custom:0123456789abcdef" not in keys_on(c, g) for g in (1, 2, 4))
    r = c.post("/roadmap/toggle", data={"key": "custom:0123456789abcdef"}, follow_redirects=False)
    assert r.headers["location"] == "/roadmap?open=3#item-custom-0123456789abcdef" and keys_on(c, 3)["custom:0123456789abcdef"] is True
    r = c.post("/roadmap/custom/delete", data={"key": "custom:0123456789abcdef"}, follow_redirects=False)
    assert r.headers["location"] == "/roadmap?open=3#grade-3" and "custom:0123456789abcdef" not in keys_on(c, 3)


def test_cannot_touch_other_users_items():
    alice, bob = make_user(nickname="앨리스"), make_user(nickname="밥")
    alice.post("/roadmap/custom", data={"text": "앨리스의 항목", "grade": "2"})
    alice_key = [k for k in keys_on(alice, 2) if k.startswith("custom:")][0]
    assert bob.post("/roadmap/toggle", data={"key": alice_key}).status_code == 404
    assert bob.post("/roadmap/custom/delete", data={"key": alice_key}).status_code == 404
    assert "앨리스의 항목" not in bob.get("/roadmap?open=all").text
    assert keys_on(alice, 2)[alice_key] is False                          # 앨리스 것은 그대로
    stranger = TestClient(app)
    assert stranger.get("/roadmap", follow_redirects=False).headers["location"] == "/profile/new"
    assert stranger.post("/roadmap/custom", data={"text": "x", "grade": "1"}, follow_redirects=False).status_code == 303


def test_custom_text_is_escaped():
    c = make_user()
    c.post("/roadmap/custom", data={"text": "<script>alert(1)</script>", "grade": "1"})
    html = c.get("/roadmap").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_delete_profile_removes_roadmap():
    c = make_user()
    c.post("/roadmap/custom", data={"text": "지워질 항목", "grade": "4"})
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
    secs = sections(c)
    assert secs[2]["now"] and secs[1]["keys"][key] is True                 # 2학년이 돼도 1학년 구역에 체크가 그대로
    c.post("/profile", data={**form, "grade": 1})
    assert keys_on(c)[key] is True


def test_me_shows_current_grade_progress():
    c = make_user(grade=2)
    c.post("/roadmap/toggle", data={"key": data.COMMON[2][0][0]})
    c.post("/roadmap/toggle", data={"key": data.COMMON[3][0][0]})        # 다른 학년 체크는 /me 숫자에 안 들어감
    done, total = progress(c, 2)
    assert done == 1 and f'href="/roadmap">이번 학기 로드맵 <b>{done}/{total}</b>' in c.get("/me").text


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
