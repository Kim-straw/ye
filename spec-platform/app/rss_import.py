"""학교 게시판 RSS를 읽어 교내 프로그램(opportunities)에 넣기.

RSS = 게시판 앞의 무료 전단지 꽂이. 로그인 없이 열리는 주소만 FEEDS에 넣습니다.
실행: python -m app.rss_import   (spec-platform 폴더에서, 인터넷 필요)

한계 (규칙 기반이라 완벽하지 않음):
- RSS에는 마감일·난이도·소요시간이 없음 -> 비워 두고 화면에 "원문 확인"으로 표시
- 태그는 제목/본문 키워드로 추정
- 수상작 발표 같은 '프로그램이 아닌 글'은 제외 키워드로 거름
"""
import re
import urllib.request
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as ET  # 외부 XML 공격(XXE 등)을 막아 주는 안전한 파서
from sqlalchemy import select

from .db import Opportunity, School, SessionLocal, Spec, Tag, init_db

# 로그인 없이 열리는 것을 직접 확인한 게시판만 넣기
FEEDS = [
    {"url": "https://nipa.korea.ac.kr/bbs/fieldwork/575/rssList.do?row=50",
     "base": "https://nipa.korea.ac.kr", "host": "세종현장실습지원센터", "category": "현장실습"},
    # 아래 4곳은 검색 결과의 글 주소에서 게시판 번호만 따온 것이라 열리는지 아직 확인하지 못함.
    # 안 열리면(로그인 필요 등) 실행할 때 [실패]로 알려 주고 나머지는 계속 진행함. 계속 실패하면 이 줄을 지우면 됨.
    {"url": "https://nipa.korea.ac.kr/bbs/fieldwork/868/rssList.do?row=50", "base": "https://nipa.korea.ac.kr", "host": "세종현장실습지원센터", "category": "현장실습"},
    {"url": "https://innovation.korea.ac.kr/bbs/innovation/189/rssList.do?row=50", "base": "https://innovation.korea.ac.kr", "host": "RISE 사업단", "category": "창업"},
    {"url": "https://software.korea.ac.kr/bbs/software/352/rssList.do?row=50", "base": "https://software.korea.ac.kr", "host": "소프트웨어 관련 사이트", "category": "특강"},
    {"url": "https://career.korea.ac.kr/bbs/cdc/526/rssList.do?row=50", "base": "https://career.korea.ac.kr", "host": "career.korea.ac.kr", "category": "취업"},
]

# 이 단어가 제목에 있으면 '프로그램 모집'이 아닌 글로 보고 제외
EXCLUDE = ["수상작", "결과", "합격자", "선정자", "명단", "폐강", "휴무"]

# 키워드 -> 태그 (AI를 붙이면 이 부분을 대체할 수 있음)
TAG_KEYWORDS = {
    "개발": ["SW", "소프트웨어", "개발", "코딩", "프로그래밍", "해커톤"],
    "데이터": ["데이터", "분석", "빅데이터"],
    "AI": ["AI", "인공지능", "머신러닝"],
    "마케팅": ["마케팅", "홍보", "SNS", "서포터즈"],
    "경영": ["경영", "기업", "현장실습", "인턴", "직무"],
    "글쓰기": ["수기", "글쓰기", "에세이", "기자"],
    "디자인": ["디자인"],
    "창업": ["창업", "스타트업", "예비창업"],
    "공공": ["공공기관", "정책", "공기업"],
    "봉사": ["봉사"],
    "어학": ["토익", "TOEIC", "영어", "어학", "OPIc"],
    "상담": ["상담"],
    "리더십": ["리더십", "멘토", "멘토링"],
    "영상": ["영상", "유튜브", "숏폼"],
}
SPEC_KEYWORDS = {
    "인턴 경험": ["현장실습", "인턴"],
    "공모전 수상": ["공모전", "경진대회"],
    "창업 경험": ["창업"],
    "봉사활동 경험": ["봉사"],
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "spec-platform-student-project"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()  # 학교 형식: 2026-02-27 17:13:47.0
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()  # 표준 RSS 형식: Fri, 27 Feb 2026 ...
    except (TypeError, ValueError):
        return None


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def parse_rss(xml_text: str, base: str) -> list[dict]:
    """RSS 글자 덩어리 -> [{title, url, posted_at, description}, ...]"""
    if "<rss" not in xml_text[:2000] and "<channel" not in xml_text[:2000]:
        raise ValueError("RSS가 아닌 응답입니다 (로그인이 필요하거나 게시판 주소가 다름)")
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if link.startswith("/"):  # 학교 RSS는 링크가 /bbs/... 로 시작 -> 사이트 주소를 앞에 붙임
            link = base + link
        items.append({"title": title, "url": link, "posted_at": parse_date(it.findtext("pubDate")),
                      "description": clean(it.findtext("description"))[:500]})
    return items


def is_program(title: str) -> bool:
    return not any(word in title for word in EXCLUDE)


def guess(text: str, table: dict[str, list[str]]) -> list[str]:
    return [name for name, words in table.items() if any(w.lower() in text.lower() for w in words)]


def save_items(db, items: list[dict], feed: dict) -> int:
    school = db.scalars(select(School)).first()
    tags = {t.name: t for t in db.scalars(select(Tag))}
    specs = {s.name: s for s in db.scalars(select(Spec))}
    known = set(db.scalars(select(Opportunity.url).where(Opportunity.source == "rss")))
    added = 0
    for item in items:
        if item["url"] in known or not is_program(item["title"]):
            continue  # 이미 넣은 글이거나 프로그램이 아닌 글
        text = item["title"] + " " + item["description"]
        db.add(Opportunity(
            school_id=school.id if school else None, scope="교내", category=feed["category"],
            title=item["title"], host=feed["host"], description=item["description"],
            difficulty=None, hours=None, deadline=None, posted_at=item["posted_at"],
            url=item["url"], source="rss", is_sample=False,
            tags=[tags[n] for n in guess(text, TAG_KEYWORDS) if n in tags],
            specs=[specs[n] for n in guess(text, SPEC_KEYWORDS) if n in specs],
        ))
        known.add(item["url"])
        added += 1
    db.commit()
    return added


def run():
    init_db()
    db = SessionLocal()
    for feed in FEEDS:
        board = feed["url"].split("/bbs/")[1].split("/rssList")[0]  # 예: fieldwork/575 (게시판 구분용)
        label = f"{feed['host']} ({board})"
        try:
            items = parse_rss(fetch(feed["url"]), feed["base"])
        except Exception as e:  # 한 게시판이 실패해도 나머지는 계속
            print(f"[실패] {label}: {e}")
            continue
        added = save_items(db, items, feed)
        print(f"[완료] {label}: 글 {len(items)}개 중 새 프로그램 {added}개 추가")
    db.close()


if __name__ == "__main__":
    run()
