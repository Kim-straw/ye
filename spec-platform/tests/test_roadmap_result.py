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
    assert [p["key"] for p in data.PATHS] == ["finance", "public", "grad", "dev", "data_ai", "research", "marketing", "startup"]
    sentences = []
    for p in data.PATHS:
        assert re.fullmatch(r"[a-z0-9_]{3,20}", p["key"]) and p["name"] and p["intro"]
        assert set(p["steps"]) == {1, 2, 3, 4} and all(len(v) == 3 for v in p["steps"].values()), p["key"]
        assert set(p["link"]) <= {"q", "sector"} and p["link"]
        sentences += [p["intro"]] + [t for v in p["steps"].values() for t in v]
    assert len(sentences) == 8 + 96
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
