"""2단계 카테고리 바: 상위 4개 중 지금 화면 하나만 선택, 하위는 DB에 실제 있는 분류만, 조건 유지·초기화 규칙"""
import re
from datetime import date

from fastapi.testclient import TestClient

from app import rss_import, seed
from app.db import SessionLocal
from app.main import app

TOPS = ["전체", "교내", "대외활동", "인턴·채용"]


def add(title, category, scope="교내", days_ago=0):
    db = SessionLocal()
    xml = (f'<rss><channel><item><title>{title}</title><link>/bbs/t/{abs(hash(title))}/artclView.do</link>'
           f'<pubDate>{date.fromordinal(date.today().toordinal() - days_ago)} 09:00:00.0</pubDate></item></channel></rss>')
    rss_import.save_items(db, rss_import.parse_rss(xml, "https://sejong.korea.ac.kr"), {"host": "시험 게시판", "category": category, "scope": scope})
    db.close()


def catbar(html):
    """페이지에서 카테고리 바 부분만 꺼내 (상위 [(이름, 주소, 선택)], 하위 [...]) 로"""
    nav = re.search(r'<nav class="catbar".*?</nav>', html, re.S).group(0)
    def rows(cls):
        m = re.search(rf'<div class="{cls}">(.*?)</div>', nav, re.S)
        if not m:
            return []
        return [(name, href.replace("&amp;", "&"), "aria-current" in attrs)
                for href, attrs, name in re.findall(r'<a href="([^"]*)"([^>]*)>([^<]*)</a>', m.group(1))]
    return rows("catbar-top"), rows("catbar-sub")


def setup_function():
    seed.run()


def test_top_row_marks_only_current_screen():
    c = TestClient(app)
    for url, expected in [("/opportunities", "전체"), ("/opportunities?scope=교내", "교내"),
                          ("/opportunities?scope=외부", "대외활동"), ("/recruit", "인턴·채용")]:
        top, _ = catbar(c.get(url).text)
        assert [t[0] for t in top] == TOPS
        assert [t[0] for t in top if t[2]] == [expected], url


def test_sub_row_uses_real_categories_only():
    add("시험 교내 특강", "특강")
    add("시험 교내 행사", "교내행사")
    add("시험 대외 공고", "외부기관공고", scope="외부")
    c = TestClient(app)
    _, sub = catbar(c.get("/opportunities?scope=교내").text)
    db_categories = {"특강", "교내행사", "현장실습"}  # seed의 실제 공지 스냅샷(현장실습) + 테스트에서 넣은 2개
    assert [s[0] for s in sub][0] == "전체" and set(s[0] for s in sub[1:]) == db_categories
    assert "공모전" not in [s[0] for s in sub]             # DB에 없는 분류 이름은 만들지 않음
    _, sub_out = catbar(c.get("/opportunities?scope=외부").text)
    assert sub_out == []                                    # 대외활동 분류가 1개뿐 -> '전체'와 같으므로 하위 줄 없음
    _, sub_all = catbar(c.get("/opportunities").text)
    assert sub_all == []                                    # 상위 '전체'에는 하위 줄 없음


def test_sub_selection_and_links_keep_conditions():
    c = TestClient(app)
    html = c.get("/recruit", params={"sector": "공공·공기업", "q": "인턴", "region": "서울", "show_closed": "true"}).text
    top, sub = catbar(html)
    assert [s[0] for s in sub] == ["전체", "공공·공기업", "사기업", "대학·교육", "기타"]
    assert [s[0] for s in sub if s[2]] == ["공공·공기업"]
    private = dict((s[0], s[1]) for s in sub)["사기업"]
    assert "q=%EC%9D%B8%ED%84%B4" in private and "region=%EC%84%9C%EC%9A%B8" in private and "show_closed=true" in private
    # 상위 링크는 show_closed만 가져가고 하위·검색 조건은 초기화
    tops = dict((t[0], t[1]) for t in top)
    assert tops["교내"] == "/opportunities?scope=%EA%B5%90%EB%82%B4&show_closed=true"
    assert tops["인턴·채용"] == "/recruit?show_closed=true"
    assert all("q=" not in h and "sector=" not in h and "region=" not in h for h in tops.values())


def test_old_urls_still_work():
    add("시험 대외 공고 A", "외부기관공고", scope="외부", days_ago=400)
    c = TestClient(app)
    r = c.get("/opportunities", params={"scope": "외부", "category": "외부기관공고", "show_closed": "true"})
    assert r.status_code == 200 and "시험 대외 공고 A" in r.text
    assert "시험 대외 공고 A" not in c.get("/opportunities", params={"scope": "외부", "category": "외부기관공고"}).text  # 오래된 글은 기본 목록에서 빠짐
    assert c.get("/recruit", params={"kind": "인턴", "mine": "true"}).status_code == 200


def test_progress_script_is_loaded_and_served():
    c = TestClient(app)
    html = c.get("/").text
    assert '<script src="/static/progress.js" defer></script>' in html
    js = c.get("/static/progress.js")
    assert js.status_code == 200 and "loadbar" in js.text
    assert ".value" not in js.text and "password" not in js.text.lower()  # 입력값을 읽지 않음
    sw = c.get("/sw.js").text
    assert re.search(r'const CACHE = "specroad-v\d+"', sw) and "/static/progress.js" in sw  # 버전 숫자는 정적 파일을 바꿀 때마다 올라감
