"""자동 점검: 사용자가 프로필 만들기 -> 추천 -> 갭 분석까지 가는 흐름을 가짜 브라우저로 돌려 봄.
실행: python -m pytest -q   (spec-platform 폴더에서, 먼저 python -m app.seed)
"""
from fastapi.testclient import TestClient

from app import seed
from app.main import app

seed.run()
client = TestClient(app)


def make_profile():
    # 컴퓨터융합소프트웨어학과(id=1), 관심: 마케팅(id=4), 스펙: SQLD(id=2) + TOEIC(id=6) 650점
    return client.post("/profile", data={
        "nickname": "테스트", "department_id": 1, "grade": 3, "admission_year": 2024, "gpa": "3.5",
        "tag_ids": ["4"], "spec_ids": ["2", "6"], "score_6": "650",
    }, follow_redirects=False)


def test_pages_without_profile():
    assert client.get("/").status_code == 200
    assert client.get("/opportunities").status_code == 200
    r = client.get("/me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/profile/new"
    assert client.get("/api/me").status_code == 401


def test_full_flow():
    r = make_profile()
    assert r.status_code == 303 and "user_id" in r.cookies
    client.cookies.set("user_id", r.cookies["user_id"])

    assert "우리 학교 프로그램" in client.get("/me").text
    recs = client.get("/api/recommendations", params={"scope": "교내"}).json()
    assert recs and all(x["scope"] == "교내" for x in recs)
    assert recs == sorted(recs, key=lambda x: -x["score"])

    # 공기업 전산직(id=4): 정보처리기사 필수(없음), TOEIC 700 필수(650 -> 부족)
    gap = client.get("/api/gap/4").json()
    status = {i["spec"]: i["status"] for i in gap["items"]}
    assert status["정보처리기사"] == "없음" and status["TOEIC"] == "부족"
    assert gap["required_rate"] == 0
    toeic = next(i for i in gap["items"] if i["spec"] == "TOEIC")
    assert any("토익" in f["title"] for f in toeic["fillers"])
    assert client.get("/gap/4").status_code == 200

    # 후기 작성
    r = client.post("/opportunities/1/reviews", data={"rating": 4, "content": "테스트 후기입니다"}, follow_redirects=False)
    assert r.status_code == 303
    assert "테스트 후기입니다" in client.get("/opportunities/1").text


def test_closed_opportunity_hidden():
    assert "영상 크리에이터" not in client.get("/opportunities").text
    assert "영상 크리에이터" in client.get("/opportunities", params={"show_closed": "true"}).text
