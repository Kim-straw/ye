"""RSS 수집 점검. 실제 학교 사이트 대신, 직접 확인한 RSS와 같은 구조의 가짜 XML을 씀."""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import rss_import, seed
from app.db import Opportunity, SessionLocal
from app.main import app
from tests.helpers import dept_id

FEED = rss_import.NIPA_575
RECENT = (date.today() - timedelta(days=10)).isoformat()

# nipa.korea.ac.kr/bbs/fieldwork/575/rssList.do 화면과 같은 구조 (+ 최근 모집 글 1개)
SAMPLE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>RSS 게시판 2.0</title><link>/webhome/koreaSejong/sites/fieldwork/</link>
<description><![CDATA[ This is RSS Board. ]]></description><language>ko</language>
<item><title><![CDATA[ 2027 동계 현장실습학기제 참여 학생 모집 ]]></title>
<link>/bbs/fieldwork/575/999999/artclView.do?layout=unknown</link>
<pubDate>{RECENT} 09:00:00.0</pubDate><author>세종현장실습지원센터</author>
<description><![CDATA[ 공공기관 및 기업 현장실습 참여 학생을 모집합니다. ]]></description></item>
<item><title><![CDATA[ 제4회 현장실습학기제 우수 수기 공모전 수상작 및 인터뷰 ]]></title>
<link>/bbs/fieldwork/575/267131/artclView.do?layout=unknown</link>
<pubDate>2026-02-27 17:13:47.0</pubDate><author>세종현장실습지원센터</author>
<description><![CDATA[ 수상작 안내 ]]></description></item>
<item><title><![CDATA[ 제4회 현장실습학기제 우수사례 수기·영상 공모전 개최 ]]></title>
<link>/bbs/fieldwork/575/263629/artclView.do?layout=unknown</link>
<pubDate>2025-10-22 09:19:29.0</pubDate><author>세종현장실습지원센터</author>
<description><![CDATA[ 세종현장실습온라인시스템 바로가기 ]]></description></item>
</channel></rss>"""


def fresh_db_with_rss():
    seed.run()
    db = SessionLocal()
    items = rss_import.parse_rss(SAMPLE_XML, FEED["base"])
    added = rss_import.save_items(db, items, FEED)
    return db, items, added


def test_parse():
    items = rss_import.parse_rss(SAMPLE_XML, FEED["base"])
    assert len(items) == 3
    assert items[1]["url"] == "https://nipa.korea.ac.kr/bbs/fieldwork/575/267131/artclView.do?layout=unknown"
    assert items[1]["posted_at"] == date(2026, 2, 27)
    assert items[0]["title"] == "2027 동계 현장실습학기제 참여 학생 모집"


def test_save_filters_and_no_duplicates():
    db, items, added = fresh_db_with_rss()
    assert added == 1  # 수상작 글 제외 + '공모전 개최' 글은 seed 스냅샷에 이미 있어서 중복 제외
    assert rss_import.save_items(db, items, FEED) == 0  # 두 번 넣어도 중복 없음
    rows = db.scalars(select(Opportunity).where(Opportunity.source == "rss")).all()
    recent = next(o for o in rows if "모집" in o.title)
    assert {t.name for t in recent.tags} >= {"경영", "공공"}
    assert "인턴 경험" in {s.name for s in recent.specs}
    assert recent.is_sample is False and recent.deadline is None
    db.close()


def test_rss_items_in_app():
    fresh_db_with_rss()[0].close()
    client = TestClient(app)
    # 융합경영학부 글로벌경영전공(기본 태그: 경영) -> 최근 현장실습 공지가 추천되어야 함
    r = client.post("/profile", data={"nickname": "rss", "department_id": dept_id("융합경영학부 글로벌경영전공"), "grade": 2, "admission_year": 2025},
                    follow_redirects=False)
    client.cookies.set("user_id", r.cookies["user_id"])
    recs = client.get("/api/recommendations", params={"scope": "교내"}).json()
    assert any(x["source"] == "rss" and "모집" in x["title"] for x in recs)

    page = client.get("/opportunities").text
    assert "2027 동계 현장실습학기제" in page          # 최근 공지는 보임
    assert "우수사례 수기" not in page                 # 2025년 공지는 기본 목록에서 숨김
    assert "우수사례 수기" in client.get("/opportunities", params={"show_closed": "true"}).text

    rid = next(x["id"] for x in recs if x["source"] == "rss")
    detail = client.get(f"/opportunities/{rid}").text
    assert "원문 공고 보기" in detail and "학교 공지" in detail

    # 갭 분석에서도 오류 없이 (마감일 없는 활동이 섞여 있어도)
    for job_id in range(1, 6):
        assert client.get(f"/gap/{job_id}").status_code == 200


def test_run_survives_network_error(monkeypatch, capsys):
    seed.run()
    monkeypatch.setattr(rss_import, "fetch", lambda url: (_ for _ in ()).throw(OSError("연결 실패")))
    rss_import.run()
    assert "[실패]" in capsys.readouterr().out


def test_external_feed_goes_to_outside_activities():
    """외부기관공고 게시판(scope=외부)은 교내가 아니라 대외활동으로 저장되고, 학교 RSS의 이중 기호(&amp;#9312;)는 ①로 읽혀야 함"""
    seed.run()
    xml = ('<rss version="2.0"><channel><item><title><![CDATA[ 2027 대학생 서포터즈 모집 ]]></title>'
           '<link>/bbs/koreaSejong/663/1/artclView.do</link><pubDate>2026-11-10 09:00:00.0</pubDate>'
           '<description><![CDATA[ &amp;#9312; 실내 &amp;#9313; 야외 ]]></description></item></channel></rss>')
    feed = {"url": "https://sejong.korea.ac.kr/bbs/koreaSejong/663/rssList.do?row=50", "base": "https://sejong.korea.ac.kr",
            "host": "세종캠퍼스 외부기관공고", "category": "외부기관공고", "scope": "외부"}
    items = rss_import.parse_rss(xml, feed["base"])
    assert items[0]["description"] == "① 실내 ② 야외"
    db = SessionLocal()
    assert rss_import.save_items(db, items, feed) == 1
    row = db.scalars(select(Opportunity).where(Opportunity.url == items[0]["url"])).one()
    assert row.scope == "외부" and row.school_id is None
    assert [FEED["host"]] == [rss_import.FEEDS[3]["host"]]  # nipa 게시판이 목록에 그대로 있음
    db.close()


def test_outside_filter_drops_non_student_posts():
    """대외활동(외부) 게시판에서 업체·교직원·전문가 대상 글은 거르고, 학생 대상 글은 남겨야 함. 교내 게시판의 '교수 특강'은 영향 없음"""
    seed.run()
    feed = {"url": "https://sejong.korea.ac.kr/bbs/koreaSejong/663/rssList.do?row=50", "base": "https://sejong.korea.ac.kr",
            "host": "세종캠퍼스 외부기관공고", "category": "외부기관공고", "scope": "외부"}
    titles = ["2027 청년 서포터즈 모집", "OO청사 청소 용역 입찰 공고", "2027 참여기업 모집", "외부 평가위원 모집", "대학생 공모전 안내"]
    items = [{"title": t, "url": f"https://x.test/{i}", "posted_at": date.today(), "description": ""} for i, t in enumerate(titles)]
    db = SessionLocal()
    assert rss_import.save_items(db, items, feed) == 2
    saved = set(db.scalars(select(Opportunity.title).where(Opportunity.scope == "외부", Opportunity.source == "rss")))
    assert saved == {"2027 청년 서포터즈 모집", "대학생 공모전 안내"}
    assert rss_import.is_program("교수 특강 안내", "교내")

    # 기준이 생기기 전에 저장된 글도 정리됨
    db.add(Opportunity(scope="외부", category="외부기관공고", title="연구과제 공모 안내", host="h", url="https://x.test/old",
                       source="rss", posted_at=date.today()))
    db.commit()
    assert rss_import.cleanup_outside(db) == 1
    db.close()
