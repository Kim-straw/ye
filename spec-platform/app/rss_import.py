"""학교 게시판 RSS를 읽어 교내 프로그램(opportunities)에 넣기.

RSS = 게시판 앞의 무료 전단지 꽂이. 로그인 없이 열리는 주소만 FEEDS에 넣습니다.
실행: python -m app.rss_import   (spec-platform 폴더에서, 인터넷 필요)

한계 (규칙 기반이라 완벽하지 않음):
- RSS에는 마감일·난이도·소요시간이 없음 -> 비워 두고 화면에 "원문 확인"으로 표시
- 태그는 제목/본문 키워드로 추정
- 수상작 발표 같은 '프로그램이 아닌 글'은 제외 키워드로 거름
"""
import html
import re
import urllib.request
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as ET  # 외부 XML 공격(XXE 등)을 막아 주는 안전한 파서
from sqlalchemy import select

from .db import Opportunity, School, SessionLocal, Spec, Tag, init_db

# seed.py의 스냅샷과 테스트가 이 게시판을 기준으로 씀
NIPA_575 = {"url": "https://nipa.korea.ac.kr/bbs/fieldwork/575/rssList.do?row=50",
            "base": "https://nipa.korea.ac.kr", "host": "세종현장실습지원센터", "category": "현장실습"}

# 로그인 없이 열리는 게시판만 넣기. 안 열리면 실행할 때 [실패]로 알려 주고 나머지는 계속 진행함.
# scope를 적지 않으면 "교내". 외부기관 공고처럼 학교 밖 활동이면 "외부"(= 대외활동 목록).
FEEDS = [
    # 세종캠퍼스 홈페이지 > KUS 소식 (657은 2026-11-13 브라우저에서 열림 확인, 660·663은 미확인)
    {"url": "https://sejong.korea.ac.kr/bbs/koreaSejong/657/rssList.do?row=50",
     "base": "https://sejong.korea.ac.kr", "host": "세종캠퍼스 교내행사공지", "category": "교내행사"},
    {"url": "https://sejong.korea.ac.kr/bbs/koreaSejong/660/rssList.do?row=50",
     "base": "https://sejong.korea.ac.kr", "host": "세종캠퍼스 학생진로취업공지", "category": "진로취업"},
    {"url": "https://sejong.korea.ac.kr/bbs/koreaSejong/663/rssList.do?row=50",
     "base": "https://sejong.korea.ac.kr", "host": "세종캠퍼스 외부기관공고", "category": "외부기관공고", "scope": "외부"},
    # 하위 사이트 (2026-11-13 내 PC에서 수집 성공 확인)
    NIPA_575,
    {"url": "https://nipa.korea.ac.kr/bbs/fieldwork/868/rssList.do?row=50", "base": "https://nipa.korea.ac.kr", "host": "세종현장실습지원센터", "category": "현장실습"},
    {"url": "https://innovation.korea.ac.kr/bbs/innovation/189/rssList.do?row=50", "base": "https://innovation.korea.ac.kr", "host": "RISE 사업단", "category": "창업"},
    {"url": "https://software.korea.ac.kr/bbs/software/352/rssList.do?row=50", "base": "https://software.korea.ac.kr", "host": "소프트웨어 관련 사이트", "category": "특강"},
    {"url": "https://career.korea.ac.kr/bbs/cdc/526/rssList.do?row=50", "base": "https://career.korea.ac.kr", "host": "career.korea.ac.kr", "category": "취업"},
]

# 이 단어가 제목에 있으면 '프로그램 모집'이 아닌 글로 보고 제외
EXCLUDE = ["수상작", "결과", "합격자", "선정자", "명단", "폐강", "휴무"]

# 외부기관공고(대외활동)에만 추가로 거르는 단어: 학생이 아니라 기업·교직원·전문가를 찾는 글
# (실제 게시판 글을 다 보고 정한 목록이 아니라 흔한 유형으로 정한 1차 기준. 걸러진 글은 run() 출력에 개수로 나옴)
OUTSIDE_EXCLUDE = [
    "입찰", "용역", "조달", "계약 공고", "공사",                      # 업체 대상
    "참여기업", "수요기업", "입주기업", "기업 모집", "기업 대상", "기업체 모집",
    "교원 채용", "교원 초빙", "교수 초빙", "전임교원", "교직원",          # 교직원 대상
    "평가위원", "심사위원", "자문위원", "전문위원", "위원 모집", "위원 위촉",  # 전문가 대상
    "연구과제", "과제 공모", "연구자 모집",                             # 연구자(교수) 대상
    "시스템 점검", "사무실 이전", "이전 안내", "휴관",                    # 안내문
]

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
    "반도체": ["반도체", "디스플레이", "전자", "소자"],
    "바이오·보건": ["바이오", "생명", "보건", "헬스케어", "약학", "신약", "식품", "의료"],
    "환경": ["환경", "탄소", "친환경", "에너지", "ESG"],
    "스포츠": ["스포츠", "체육", "운동"],
    "문화·예술": ["문화", "예술", "전시", "박물관", "문화재", "공연"],
    "통계": ["통계", "빅데이터"],
    "보안": ["보안", "사이버", "해킹"],
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


DEADLINE_RE = re.compile(r"~\s*(\d{1,2})\s*[/.]\s*(\d{1,2})")


def parse_deadline(title: str, posted_at: date | None) -> date | None:
    """제목 속 '(~11/24)', '(~11/30 17:00)', '(~11.19)' 같은 표기를 마감일로 읽음.
    연도는 적혀 있지 않아서 게시일의 해로 보고, 게시일보다 한 달 넘게 앞서면 다음 해로 봄(12월 게시 → 1월 마감).
    '(11/25~26)'처럼 행사 기간이나 '채용 시 마감'은 마감일이 아니므로 None."""
    m = DEADLINE_RE.search(title or "")
    if not m or posted_at is None:
        return None
    try:
        d = date(posted_at.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    if d < posted_at - timedelta(days=30):
        try:
            d = date(posted_at.year + 1, d.month, d.day)
        except ValueError:
            return None
    return d


def clean_title(title: str) -> str:
    return title.strip().rstrip("}").strip()  # 이 게시판은 제목 끝에 '}'가 붙어 옴


def backfill_deadlines(db) -> int:
    """마감일 표기 기능이 생기기 전에 저장된 글의 마감일과 제목 끝 '}'를 채움"""
    n = 0
    for o in db.scalars(select(Opportunity).where(Opportunity.source == "rss")):
        changed = False
        t = clean_title(o.title)
        if t != o.title:
            o.title, changed = t, True
        if o.deadline is None:
            d = parse_deadline(o.title, o.posted_at)
            if d:
                o.deadline, changed = d, True
        n += changed
    db.commit()
    return n


def clean(text: str | None) -> str:
    text = html.unescape(html.unescape(text or ""))  # 학교 RSS는 &amp;#9312; 처럼 두 번 감싼 기호가 있음 -> ①
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def parse_rss(xml_text: str, base: str) -> list[dict]:
    """RSS 글자 덩어리 -> [{title, url, posted_at, description}, ...]"""
    if "<rss" not in xml_text[:2000] and "<channel" not in xml_text[:2000]:
        raise ValueError("RSS가 아닌 응답입니다 (로그인이 필요하거나 게시판 주소가 다름)")
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        title = clean_title(clean(it.findtext("title")))
        link = (it.findtext("link") or "").strip()
        if link.startswith("/"):  # 학교 RSS는 링크가 /bbs/... 로 시작 -> 사이트 주소를 앞에 붙임
            link = base + link
        items.append({"title": title, "url": link, "posted_at": parse_date(it.findtext("pubDate")),
                      "description": clean(it.findtext("description"))[:500]})
    return items


def is_program(title: str, scope: str = "교내") -> bool:
    """학생이 참여할 수 있는 프로그램 글인지. 대외활동(외부)은 업체·교직원 대상 글을 한 번 더 거름"""
    words = EXCLUDE + OUTSIDE_EXCLUDE if scope == "외부" else EXCLUDE
    return not any(word in title for word in words)


def cleanup_outside(db) -> int:
    """기준이 바뀌기 전에 이미 저장된 대외활동 중 거를 글을 지움 (후기가 달린 글은 남김)"""
    rows = db.scalars(select(Opportunity).where(Opportunity.scope == "외부", Opportunity.source == "rss")).all()
    removed = 0
    for o in rows:
        if not o.reviews and not is_program(o.title, "외부"):
            db.delete(o)
            removed += 1
    db.commit()
    return removed


def guess(text: str, table: dict[str, list[str]]) -> list[str]:
    return [name for name, words in table.items() if any(w.lower() in text.lower() for w in words)]


def save_items(db, items: list[dict], feed: dict) -> int:
    school = db.scalars(select(School)).first()
    tags = {t.name: t for t in db.scalars(select(Tag))}
    specs = {s.name: s for s in db.scalars(select(Spec))}
    known = set(db.scalars(select(Opportunity.url).where(Opportunity.source == "rss")))
    added = 0
    for item in items:
        scope = feed.get("scope", "교내")
        if item["url"] in known or not is_program(item["title"], scope):
            continue  # 이미 넣은 글이거나 프로그램이 아닌 글
        text = item["title"] + " " + item["description"]
        db.add(Opportunity(
            school_id=school.id if (school and scope == "교내") else None, scope=scope, category=feed["category"],
            title=item["title"], host=feed["host"], description=item["description"],
            difficulty=None, hours=None, deadline=parse_deadline(item["title"], item["posted_at"]), posted_at=item["posted_at"],
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
    filled = backfill_deadlines(db)
    if filled:
        print(f"[정리] 제목의 마감일 표기를 읽어 {filled}개 글 갱신")
    removed = cleanup_outside(db)
    if removed:
        print(f"[정리] 학생 대상이 아닌 대외활동 {removed}개 삭제")
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
