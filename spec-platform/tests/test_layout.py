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


def add(title, scope="외부", category="대외활동", deadline=None, posted=0, host="시험기관", desc=""):
    db = SessionLocal()
    o = Opportunity(scope=scope, category=category, title=title, host=host, source="manual", description=desc,
                    url="https://example.org/" + title, posted_at=date.today() - timedelta(days=posted),
                    deadline=(date.today() + timedelta(days=deadline)) if deadline is not None else None)
    db.add(o); db.commit(); oid = o.id; db.close()
    return oid


def titles(html):
    return re.findall(r'<h3 class="item-title">([^<]+)</h3>', html)


def test_list_filters_search_period_region_and_old_urls():
    add("가 서포터즈", category="서포터즈", deadline=3)
    add("나 기자단", category="기자단", deadline=20, desc="서울 본사")
    add("다 마감없음", category="기자단")
    add("라 지난글", category="기자단", deadline=-2)
    c = TestClient(app)
    assert titles(c.get("/opportunities?scope=외부&category=서포터즈").text) == ["가 서포터즈"]           # 예전 주소(분류 하나)
    assert set(titles(c.get("/opportunities?scope=외부&category=서포터즈&category=기자단").text)) == {"가 서포터즈", "나 기자단", "다 마감없음"}
    assert titles(c.get("/opportunities?scope=외부&q=기자단&period=30").text) == ["나 기자단"]          # 검색(새) + 기간
    assert titles(c.get("/opportunities?scope=외부&period=7").text) == ["가 서포터즈"]
    assert titles(c.get("/opportunities?scope=외부&period=none").text) == ["다 마감없음"]
    assert titles(c.get("/opportunities?scope=외부&region=서울").text) == ["나 기자단"]                  # 지역(추정)
    assert "라 지난글" in titles(c.get("/opportunities?scope=외부&show_closed=true").text)
    assert c.get("/opportunities?scope=외부&period=hack&sort=hack&page=abc").status_code == 200           # 모르는 값은 기본값
    page = c.get("/opportunities?scope=외부&category=기자단&q=기자").text
    assert 'name="category" value="기자단" checked' in page and 'name="category" value="서포터즈">' in page
    assert '<input type="hidden" name="category" value="기자단">' in page.split('role="search"')[1].split("</form>")[0]  # 검색해도 필터 유지
    assert '총 <b>1</b>개' in page and "공모전" not in page.split('class="filter-form"')[1].split("</form>")[0]   # 분류는 실제 있는 것만


def test_list_sort_and_pagination():
    for i in range(45):
        add(f"글{i:02d}", deadline=i + 1, posted=i)
    c = TestClient(app)
    first = titles(c.get("/opportunities?scope=외부").text)
    assert len(first) == 20 and first[0] == "글00"                                                      # 기본: 마감 임박순
    assert titles(c.get("/opportunities?scope=외부&sort=new").text)[0] == "글00"                         # 최신순(가장 최근 게시)
    assert titles(c.get("/opportunities?scope=외부&sort=new&page=2").text)[0] == "글20"
    last = c.get("/opportunities?scope=외부&page=99").text                                              # 범위 밖 -> 마지막 쪽
    assert titles(last) == [f"글{i}" for i in range(40, 45)] and '<b aria-current="page">3</b>' in last
    p2 = c.get("/opportunities?scope=외부&sort=new&q=글&page=2").text
    assert 'href="/opportunities?scope=%EC%99%B8%EB%B6%80&amp;q=%EA%B8%80&amp;sort=new&amp;page=3"' in p2   # 쪽 링크가 조건 유지
    assert 'href="/opportunities?scope=%EC%99%B8%EB%B6%80&amp;q=%EA%B8%80"' in p2                       # 정렬 바꾸면 1쪽부터


def test_recruit_filters_and_monogram():
    from app import logic
    add("[한국전력공사] 체험형 인턴", scope="교내", category="취업", deadline=5)
    add("[네이버] 개발 인턴십", scope="교내", category="취업", deadline=9, host="career.korea.ac.kr")
    c = TestClient(app)
    assert titles(c.get("/recruit?sector=공공·공기업&sector=사기업").text) == ["[한국전력공사] 체험형 인턴", "[네이버] 개발 인턴십"]
    assert titles(c.get("/recruit?sector=사기업&period=7").text) == []
    html = c.get("/recruit").text
    assert '<span class="mono" aria-hidden="true">한</span>' in html and '<span class="mono" aria-hidden="true">네</span>' in html
    assert logic.monogram(Opportunity(title="공지", host="career.korea.ac.kr", category="취업")) == "취"
    assert logic.monogram(Opportunity(title="[kakao] 인턴", host="", category="")) == "K"
