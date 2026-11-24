"""UI 틀 개편 점검: 상단 메뉴(컴퓨터)·하단 탭(폰)·목록 필터·정렬·쪽 나눔·로드맵 단계·홈 바로가기 숫자"""
import re
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import seed
from app.db import Opportunity, SessionLocal
from app.main import app
from tests.helpers import dept_id, tag_id


def setup_function():
    seed.run()


def login(grade=1, dept="반도체물리학부", tags=("반도체",)):
    c = TestClient(app)
    r = c.post("/profile", data={"nickname": "틀", "department_id": dept_id(dept), "grade": grade,
                                 "admission_year": 2025, "tag_ids": [tag_id(t) for t in tags]}, follow_redirects=False)
    c.cookies.set("user_id", r.cookies["user_id"])
    return c


def test_shell_top_nav_and_bottom_tabs_on_every_page():
    html = TestClient(app).get("/").text
    nav = re.search(r'<nav class="topnav".*?</nav>', html, re.S).group(0)
    assert re.findall(r'href="([^"]+)"', nav) == ["/roadmap", "/opportunities?scope=외부", "/recruit", "/opportunities?scope=교내"]
    assert re.findall(r'>([^<>]+)</a>', nav) == ["로드맵", "대외활동", "인턴·채용", "교내 프로그램"]
    assert 'class="icon-btn" href="/recruit" aria-label="공고 검색"' in html and 'href="/login"' in html
    assert '<div class="tabbar">' in html and "<footer class=\"foot\">" in html and "비공식 학생 프로젝트" in html
    # 지금 화면의 메뉴만 선택 표시
    page = TestClient(app).get("/opportunities?scope=교내").text
    assert re.search(r'href="/opportunities\?scope=교내" class="on" aria-current=page>교내 프로그램', page)
    assert not re.search(r'href="/opportunities\?scope=외부" class="on"', page)
