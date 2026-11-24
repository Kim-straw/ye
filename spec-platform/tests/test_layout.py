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


def test_roadmap_stepper_next_cards_and_sidebar_for_every_grade():
    for grade, now, stage in [(1, 1, "탐색"), (2, 2, "익히기"), (3, 3, "경험"), (4, 4, "지원 준비"), (6, 4, "지원 준비")]:
        c = login(grade=grade)
        html = c.get("/roadmap").text
        assert f"<b>현재 단계 {now}/4</b><span class=\"stepper-stage\">{stage}</span>" in html, grade
        steps = re.findall(r'<li class="step( done)?( now)?">', html)
        assert [bool(d) for d, _ in steps] == [g < now for g in (1, 2, 3, 4)]       # 지난 단계만 채움
        assert [bool(n) for _, n in steps] == [g == now for g in (1, 2, 3, 4)]      # 지금 단계 하나만
        cards = re.findall(r'<a class="next-card" href="/roadmap\?open=(\d)#([^"]+)">', html)
        if now == 4:
            assert cards == [] and 'id="next"' not in html                           # 4학년(5·6학년)은 다음 단계 없음
        else:
            assert len(cards) == 3 and {g for g, _ in cards} == {str(now + 1)}
            sec = re.search(rf'<details class="rm-grade" id="grade-{now + 1}">(.*?)</details>', html, re.S).group(1)
            assert [a for _, a in cards] == re.findall(r'id="(item-[^"]+)"', sec)[:3]   # 다음 학년 앞 3개 그대로
        side = re.search(r'<nav class="rm-side-nav".*?</nav>', html, re.S).group(0)
        assert re.findall(r'href="([^"]+)"', side) == ["/roadmap?open=all", "/roadmap?open=1#grade-1", "/roadmap?open=2#grade-2",
                                                      "/roadmap?open=3#grade-3", "/roadmap?open=4#grade-4", "/roadmap/result", "/roadmap/result#paths"]
        assert re.search(rf'href="/roadmap\?open={now}#grade-{now}" class="on"', side)
        assert 'class="rm-banner" href="/roadmap/result"' in html and "상담" not in html
    c = login(grade=2)
    assert re.search(r'href="/roadmap\?open=all" class="on"', c.get("/roadmap?open=all").text)
    assert re.search(r'href="/roadmap/result" class="on"', c.get("/roadmap/result").text)


def test_home_hero_counts_and_greeting():
    add("열린 대외", deadline=5); add("지난 대외", deadline=-1)
    add("열린 교내", scope="교내", category="비교과", deadline=3)
    add("교내 인턴 모집", scope="교내", category="현장실습", deadline=4)
    db = SessionLocal()
    from sqlalchemy import func, select
    from app import logic
    ext = db.scalar(select(func.count(Opportunity.id)).where(Opportunity.scope == "외부", logic.open_clause(date.today())))
    camp = db.scalar(select(func.count(Opportunity.id)).where(Opportunity.scope == "교내", logic.open_clause(date.today())))
    rec = sum(1 for o in db.scalars(select(Opportunity)) if logic.is_recruit(o) and logic.is_open(o))
    db.close()
    c = TestClient(app)
    html = c.get("/").text
    assert "전공에서 시작하는<br>나만의 진로 지도" in html and "1분 만에 시작하기" in html and 'class="motif' in html
    cards = re.findall(r'<a class="svc-card" href="([^"]+)">.*?<b>([^<]+)</b><span>([^<]+)</span>', html, re.S)
    assert cards == [("/roadmap", "로드맵", "1~4학년 할 일"), ("/opportunities?scope=외부", "대외활동", f"열린 공고 {ext}건"),
                     ("/recruit", "인턴·채용", f"열린 공고 {rec}건"), ("/opportunities?scope=교내", "교내 프로그램", f"열린 공고 {camp}건")]
    assert f"총 <b>{ext}</b>개" in c.get("/opportunities?scope=외부").text                       # 카드 숫자 = 목록 개수
    assert f"총 <b>{rec}</b>건" in c.get("/recruit").text and f"총 <b>{camp}</b>개" in c.get("/opportunities?scope=교내").text
    u = login(grade=3)
    page = u.get("/").text
    total = int(re.search(r'<span class="step-sub">3학년 · 0/(\d+)</span>', u.get("/roadmap").text).group(1))
    assert f"틀님, 지금 할 일 {total}개" in page and "내 로드맵 보기" in page and "1분 만에 시작하기" not in page
    assert f"이번 학년 0/{total} 완료" in page
    assert page.count('<section class="') <= 4                                                      # 구역 4개 이하


def test_login_has_no_social_or_fake_buttons():
    html = TestClient(app).get("/login").text
    for word in ("카카오", "구글", "Google", "네이버로", "이메일로", "상담"):
        assert word not in html, word
    assert 'class="auth-panel"' in html and 'name="login_id"' in html and 'name="password"' in html


def test_bookmarks_toggle_isolation_next_and_cleanup():
    from sqlalchemy import select
    from app import rss_import
    from app.db import Bookmark, User
    oid = add("저장할 공고", deadline=5)
    anon = TestClient(app)
    r = anon.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": "/opportunities"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/profile/new"                   # 로그인 전 -> 프로필
    a, b = login(), login()
    assert a.post("/bookmarks/toggle", data={"opportunity_id": 999999, "next": "/"}, follow_redirects=False).status_code == 404
    r = a.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": "/opportunities?scope=외부&page=1"}, follow_redirects=False)
    from urllib.parse import unquote
    assert r.status_code == 303 and unquote(r.headers["location"]) == "/opportunities?scope=외부&page=1"
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example", "", "javascript:alert(1)"):
        r = a.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": bad}, follow_redirects=False)
        assert r.headers["location"] == "/saved", bad                                         # 사이트 밖으로 보내지 않음
        a.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": "/"})                  # 다시 원래 상태(저장됨)로
    assert "저장할 공고" in titles(a.get("/saved").text) and "저장할 공고" not in titles(b.get("/saved").text)   # 사람별로 따로
    lst = a.get("/opportunities?scope=외부").text
    assert re.search(r'value="%d">\s*<input type="hidden" name="next" value="/opportunities\?scope=%%EC%%99%%B8%%EB%%B6%%80">\s*<button type="submit" aria-pressed="true"' % oid, lst)
    assert re.search(r'value="%d">.*?aria-pressed="false"' % oid, b.get("/opportunities?scope=외부").text, re.S)
    assert 'action="/bookmarks/toggle"' not in anon.get("/opportunities?scope=외부").text      # 로그인 전에는 버튼 없음
    assert 'aria-pressed="true"' in a.get(f"/opportunities/{oid}").text
    a.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": "/"})                      # 해제
    assert titles(a.get("/saved").text) == []
    # 공고가 지워지면 저장 기록도 같이 지워짐 (cleanup_outside가 지우는 글)
    gone = add("[업체] 교직원 대상 안내", category="외부기관공고")
    db = SessionLocal(); db.add(Bookmark(user_id=db.scalars(select(User.id)).first(), opportunity_id=gone)); db.commit(); db.close()
    db = SessionLocal(); o = db.get(Opportunity, gone); o.source = "rss"; db.commit()
    rss_import.cleanup_outside(db); db.close()
    db = SessionLocal()
    assert db.get(Opportunity, gone) is None                                                   # 거르는 글이라 지워짐
    assert db.scalars(select(Bookmark).where(Bookmark.opportunity_id == gone)).first() is None
    db.close()
    # 내 정보 삭제 -> 내 저장 기록도 삭제
    b.post("/bookmarks/toggle", data={"opportunity_id": oid, "next": "/"})
    db = SessionLocal(); before = db.scalar(select(__import__("sqlalchemy").func.count(Bookmark.id))); db.close()
    b.post("/profile/delete", data={"confirm": "yes"})
    db = SessionLocal(); after = db.scalar(select(__import__("sqlalchemy").func.count(Bookmark.id))); db.close()
    assert after == before - 1
