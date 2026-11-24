"""로드맵 결과 화면: 직군 가이드 내용 규칙, 결과 계산, 진로 방향 선택, 화면, 삭제 연동"""
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import roadmap_data as data
from app import roadmap_result, seed
from app.db import RoadmapEntry, SessionLocal, User
from app.main import app
from tests.helpers import dept_id, tag_id


def test_path_guide_rules():
    assert [p["key"] for p in data.PATHS] == ["finance", "public", "civil", "grad", "research", "engineer", "dev", "data_ai",
                                              "design_ux", "marketing", "sales", "global", "media", "health", "startup"]
    sentences = []
    for p in data.PATHS:
        assert re.fullmatch(r"[a-z0-9_]{3,20}", p["key"]) and p["name"] and p["intro"]
        assert set(p["steps"]) == {1, 2, 3, 4} and all(len(v) == 3 for v in p["steps"].values()), p["key"]
        assert set(p["link"]) <= {"q", "sector"} and p["link"]
        sentences += [p["intro"]] + [t for v in p["steps"].values() for t in v]
    assert len(sentences) == 15 + 15 * 12
    assert len(set(sentences)) == len(sentences)                         # 직군끼리 문장이 겹치지 않음
    for t in sentences:
        assert len(t) <= 45, t
        assert not re.search(r"\d", t), t                                # 숫자 정보 없음 (점수·날짜·퍼센트·개수)
    assert all(k in data.PATH_BY_KEY for v in data.TAG_PATHS.values() for k in v)
    assert set(data.TAG_PATHS) <= set(seed.TAGS)


def setup_function():
    seed.run()


def make_user(grade=1, dept="반도체물리학부", tags=(), nickname="결과"):
    c = TestClient(app)
    r = c.post("/profile", data={"nickname": nickname, "department_id": dept_id(dept), "grade": grade,
                                 "admission_year": 2025, "tag_ids": [tag_id(t) for t in tags]}, follow_redirects=False)
    c.cookies.set("user_id", r.cookies["user_id"])
    return c


def user_of(nickname):
    db = SessionLocal()
    u = db.scalars(select(User).where(User.nickname == nickname)).one()
    return db, u


def test_result_computation_matches_roadmap():
    c = make_user(grade=2)
    key_a, key_b = data.COMMON[2][0][0], data.COMMON[2][1][0]
    c.post("/roadmap/toggle", data={"key": key_a})                        # 2학년 하나 완료
    c.post("/roadmap/hide", data={"key": key_b})                          # 2학년 하나 빼기
    c.post("/roadmap/custom", data={"text": "직접 넣은 3학년 항목", "grade": "3"})
    c.post("/roadmap/toggle", data={"key": data.COMMON[4][0][0]})         # 4학년 하나 완료
    db, u = user_of("결과")
    r = roadmap_result.result_for(db, u)
    db.close()
    assert r.grade == 2 and [g.grade for g in r.grades] == [1, 2, 3, 4] and [g.current for g in r.grades] == [False, True, False, False]
    g2 = r.grades[1]
    assert [i.key for i in g2.done] == [key_a] and key_b not in [i.key for i in g2.done + g2.todo]   # 뺀 항목은 안 나옴
    assert any(i.custom and i.title == "직접 넣은 3학년 항목" for i in r.grades[2].todo)            # 직접 넣은 항목 포함
    assert [i.key for i in r.now] == [i.key for i in g2.todo[:3]] and len(r.now) == 3 and key_a not in [i.key for i in r.now]
    assert r.done == 2 and r.total == sum(g.total for g in r.grades)


def test_now_items_when_all_done():
    c = make_user(grade=1)
    db, u = user_of("결과")
    from app import roadmap
    for it in roadmap.plan_for(db, u).current.items:
        c.post("/roadmap/toggle", data={"key": it.key})
    db.close()
    page = c.get("/roadmap/result").text
    assert "이번 학년 항목을 모두 했어요" in page


def test_result_page_for_every_grade():
    for grade in (1, 2, 3, 4, 6):
        page = make_user(grade=grade, nickname=f"g{grade}").get("/roadmap/result").text
        steps = re.findall(r'<li class="tl-step( now)?"', page)
        assert len(steps) == 4, grade
        now = min(grade, 4)
        assert [i + 1 for i, s in enumerate(steps) if s] == [now]         # 현재 학년만 강조 (6학년 -> 4학년)
        assert re.search(rf'<details class="rs-grade" id="rs-{now}" open>', page)
    assert TestClient(app).get("/roadmap/result", follow_redirects=False).headers["location"] == "/profile/new"
    rm = make_user(nickname="링크").get("/roadmap").text
    assert re.search(r'href="/roadmap/result" class="[^"]*" >결과 보기', rm) and 'class="rm-banner" href="/roadmap/result"' in rm


def chips(page):
    """직군 칩: {key: (체크됨, 추천)}"""
    return {m.group(1): (bool(m.group(2)), "추천" in m.group(3))
            for m in re.finditer(r'name="path" value="([a-z_]+)"( checked)?><span>(.*?)</span>', page, re.S)}


def test_choose_paths_save_replace_and_limits():
    c = make_user(grade=3, dept="반도체물리학부")               # 기본 분야: 반도체·개발 -> 연구원·공정·품질·개발 추천
    page = c.get("/roadmap/result").text
    ch = chips(page)
    assert set(ch) == set(data.PATH_BY_KEY) and not any(v[0] for v in ch.values())   # 자동 선택 안 함
    assert {k for k, v in ch.items() if v[1]} == {"research", "engineer", "dev"}
    assert "진로 방향을 고르면 학년별로 해야 할 일을 보여 드려요" in page
    r = c.post("/roadmap/paths", data={"path": ["dev", "finance"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/roadmap/result#paths"
    page = c.get("/roadmap/result").text
    assert {k for k, v in chips(page).items() if v[0]} == {"dev", "finance"}
    assert page.index('id="guide-finance"') < page.index('id="guide-dev"')            # PATHS 순서대로
    assert data.PATH_BY_KEY["dev"]["steps"][3][0] in page and 'href="/recruit?q=%EA%B8%88%EC%9C%B5"' in page
    assert re.search(r'<div class="rs-row now">\s*<span class="rs-row-grade">3학년', page)  # 현재 학년 칸 강조
    c.post("/roadmap/paths", data={"path": ["public"]})                                   # 다시 저장 -> 대체
    page = c.get("/roadmap/result").text
    assert {k for k, v in chips(page).items() if v[0]} == {"public"} and 'id="guide-dev"' not in page
    assert 'href="/recruit?sector=%EA%B3%B5%EA%B3%B5%C2%B7%EA%B3%B5%EA%B8%B0%EC%97%85"' in page
    over = c.post("/roadmap/paths", data={"path": ["dev", "finance", "grad", "public"]})
    assert over.status_code == 400 and "3개까지" in over.text
    bad = c.post("/roadmap/paths", data={"path": ["dev", "hacker"]})
    assert bad.status_code == 400 and "없는 진로 방향" in bad.text
    assert {k for k, v in chips(c.get("/roadmap/result").text).items() if v[0]} == {"public"}  # 실패하면 바뀌지 않음
    c.post("/roadmap/paths", data={})                                                     # 모두 해제
    assert "진로 방향을 고르면" in c.get("/roadmap/result").text


def test_paths_are_isolated_and_not_counted():
    alice, bob = make_user(nickname="앨리스"), make_user(nickname="밥")
    alice.post("/roadmap/paths", data={"path": ["dev", "grad", "startup"]})
    bob.post("/roadmap/paths", data={"path": ["finance"]})
    assert {k for k, v in chips(bob.get("/roadmap/result").text).items() if v[0]} == {"finance"}
    assert {k for k, v in chips(alice.get("/roadmap/result").text).items() if v[0]} == {"dev", "grad", "startup"}
    bob.post("/roadmap/paths", data={"path": []})
    assert {k for k, v in chips(alice.get("/roadmap/result").text).items() if v[0]} == {"dev", "grad", "startup"}  # 밥이 지워도 앨리스 그대로
    # path: 행은 진행도·/me 숫자·직접 넣기 제한에 섞이지 않음
    from app import roadmap
    db, u = user_of("앨리스")
    plan = roadmap.plan_for(db, u)
    assert all(not i.key.startswith("path:") for s in plan.sections for i in s.items + s.hidden)
    assert f'이번 학기 로드맵 <b>0/{plan.total}</b>' in alice.get("/me").text
    db.close()
    for i in range(20):
        assert alice.post("/roadmap/custom", data={"text": f"항목 {i}", "grade": "1"}, follow_redirects=False).status_code == 303
    assert alice.post("/roadmap/custom", data={"text": "스물한 번째", "grade": "1"}).status_code == 400


def test_custom_text_escaped_on_result_page():
    c = make_user()
    c.post("/roadmap/custom", data={"text": "<script>alert(1)</script>", "grade": "1"})
    page = c.get("/roadmap/result").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_delete_profile_removes_path_rows_and_privacy_mentions_it():
    c = make_user(nickname="삭제")
    c.post("/roadmap/paths", data={"path": ["dev", "grad"]})
    c.post("/roadmap/custom", data={"text": "지워질 항목", "grade": "2"})
    db, u = user_of("삭제")
    uid = u.id
    assert {e.item_key.split(":")[0] for e in db.scalars(select(RoadmapEntry).where(RoadmapEntry.user_id == uid))} == {"path", "custom"}
    db.close()
    c.post("/profile/delete", data={"confirm": "yes"})
    db = SessionLocal()
    assert db.scalars(select(RoadmapEntry).where(RoadmapEntry.user_id == uid)).all() == []
    db.close()
    assert "고른 진로 방향" in TestClient(app).get("/privacy").text
