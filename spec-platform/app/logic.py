"""주방 레시피: 추천 점수와 갭 분석. AI 없이 규칙(if, 덧셈)만 씁니다.

DB에서 꺼낸 재료(User, Opportunity, Job)를 받아 계산 결과만 돌려줍니다.
화면이나 주소(URL)는 모릅니다. 그래서 나중에 앱/웹 어디서든 재사용할 수 있습니다.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .db import Job, Opportunity, User

TAG_WEIGHT = 10        # 겹치는 태그 1개당 점수
ON_CAMPUS_BONUS = 5    # 교내 프로그램 가산점 (핵심 가치: 교내 정보 접근성)
URGENT_BONUS = 3       # 마감 임박 가산점
URGENT_DAYS = 14
FRESH_DAYS = 60        # 마감일 없는 학교 공지는 게시 후 60일까지만 '모집 중일 수 있음'으로 봄


def open_clause(today: date):
    """'아직 지원 가능한 활동' 조건 (DB 검색용).
    마감일이 있으면 마감 전, 없으면(학교 공지) 최근 FRESH_DAYS일 안에 올라온 글."""
    return or_(
        Opportunity.deadline >= today,
        and_(Opportunity.deadline.is_(None), Opportunity.posted_at >= today - timedelta(days=FRESH_DAYS)),
    )


def is_open(opp: Opportunity, today: date | None = None) -> bool:
    """open_clause와 같은 규칙을 파이썬으로: 마감 전이거나, 마감일 없는 글은 게시 후 FRESH_DAYS일 이내"""
    today = today or date.today()
    if opp.deadline is not None:
        return opp.deadline >= today
    return opp.posted_at is not None and (today - opp.posted_at).days <= FRESH_DAYS


# ---------- 인턴·채용 칸 ----------
RECRUIT_CATEGORIES = {"현장실습", "진로취업", "취업", "공공기관 인턴", "공공기관 채용"}
RECRUIT_WORDS = ("인턴", "채용", "현장실습")
RECRUIT_KINDS = ["현장실습", "인턴", "채용", "취업 공지"]


def is_recruit(opp: Opportunity) -> bool:
    """인턴·채용 칸에 보여 줄 글인지: 취업·현장실습 게시판 글이거나 제목에 인턴·채용·현장실습이 들어간 글"""
    return opp.category in RECRUIT_CATEGORIES or any(w in opp.title for w in RECRUIT_WORDS)


def recruit_kind(opp: Opportunity) -> str:
    text = opp.title + " " + opp.category
    if "현장실습" in text:
        return "현장실습"
    if "인턴" in text:
        return "인턴"
    if "채용" in text:
        return "채용"
    return "취업 공지"


# ---------- 분야·지역 분류 (DB에 저장하지 않고 화면에 보여 줄 때 계산) ----------
# 한계: 제목 맨 앞 [기관명]과 키워드로 추정하는 규칙이라 틀릴 수 있음.
#  - '공기업'과 '공공기관'은 제목만으로 가를 수 없어 하나(공공·공기업)로 합침
#  - [한국콜마]처럼 '한국'으로 시작하는 회사는 키워드에 '한국'을 넣지 않아 사기업으로 분류됨(공공 키워드가 없을 때)
#  - 기관명 없이 올라온 글은 '기타'
SECTORS = ["공공·공기업", "사기업", "대학·교육", "기타"]
EDU_WORDS = ("대학교", "대학원", "학교법인", "교육대")
PUBLIC_WORDS = ("공단", "공사", "공무원", "시청", "군청", "도청", "구청", "의회", "교육청", "교정청", "경찰", "소방",
                "진흥원", "재단", "연구원", "평생학습관")
EMPLOYER_RE = re.compile(r"^\s*\[([^\]]+)\]")  # 제목 맨 앞 [기관명]
LOCAL_GOV_RE = re.compile(r"(시|군|구)$")         # [양주시] 같은 지방자치단체


def employer(opp: Opportunity) -> str | None:
    m = EMPLOYER_RE.match(opp.title)
    return m.group(1).strip() if m else None


def recruit_sector(opp: Opportunity) -> str:
    name = employer(opp)
    if not name:
        return "기타"
    if any(w in name for w in EDU_WORDS):  # [대학내일]은 '대학교'가 아니므로 여기 안 걸림
        return "대학·교육"
    if any(w in name for w in PUBLIC_WORDS) or LOCAL_GOV_RE.search(name):
        return "공공·공기업"
    return "사기업"


# 세종캠퍼스 학생용이라 세종·충청을 맨 앞에
REGIONS = ["세종·충청", "서울", "경기·인천", "부산·경남", "대구·경북", "광주·전라", "강원·제주", "지역 미표기"]
REGION_WORDS = {
    "세종·충청": ["세종", "충남", "충북", "충청", "대전", "천안", "아산", "논산", "청주", "공주", "서산", "당진", "조치원", "오송"],
    "서울": ["서울"],
    "경기·인천": ["경기", "인천", "수원", "성남", "안양", "양주", "과천", "용인", "고양", "부천", "화성", "평택", "파주"],
    "부산·경남": ["부산", "경남", "울산", "창원", "김해"],
    "대구·경북": ["대구", "경북", "구미", "포항"],
    "광주·전라": ["광주", "전남", "전북", "전라", "여수", "전주"],
    "강원·제주": ["강원", "제주", "춘천", "원주"],
}


def recruit_region(opp: Opportunity) -> str:
    """제목 → 기관(host) → 본문 순으로 지역 이름을 찾음. 기업 공고는 대부분 지역이 없어 '지역 미표기'(추측해서 채우지 않음)"""
    for text in (opp.title, opp.host or "", opp.description or ""):
        for region, words in REGION_WORDS.items():
            if any(w in text for w in words):
                return region
    return "지역 미표기"


def user_tag_ids(user: User) -> set[int]:
    """내 관심 태그 + 내 학과의 기본 태그"""
    return {t.id for t in user.tags} | {t.id for t in user.department.tags}


@dataclass
class Recommendation:
    opportunity: Opportunity
    score: int
    reasons: list[str] = field(default_factory=list)  # 왜 추천했는지 (설명 가능한 추천)


def score_opportunity(user: User, opp: Opportunity, today: date | None = None) -> Recommendation:
    today = today or date.today()
    my_tags = user_tag_ids(user)
    matched = [t.name for t in opp.tags if t.id in my_tags]

    score = len(matched) * TAG_WEIGHT
    reasons = []
    if matched:
        reasons.append("관심 분야 일치: " + ", ".join(matched))
    if opp.scope == "교내":
        score += ON_CAMPUS_BONUS
        reasons.append("우리 학교 프로그램")
    if opp.deadline is not None:
        days_left = (opp.deadline - today).days
        if 0 <= days_left <= URGENT_DAYS:
            score += URGENT_BONUS
            reasons.append(f"마감 {days_left}일 전")
    if opp.source == "rss":
        reasons.append("학교 공지")
    return Recommendation(opp, score, reasons)


def sort_key(opp: Opportunity):
    """마감 빠른 순, 마감일 없는 공지는 뒤로 (최신 공지 먼저)"""
    if opp.deadline is not None:
        return (0, opp.deadline.toordinal())
    return (1, -(opp.posted_at.toordinal() if opp.posted_at else 0))


def recommend(db: Session, user: User, scope: str | None = None, limit: int = 5) -> list[Recommendation]:
    today = date.today()
    query = select(Opportunity).where(open_clause(today))  # 마감 지난 것, 오래된 공지 제외
    if scope:
        query = query.where(Opportunity.scope == scope)
    if scope == "교내":
        query = query.where(Opportunity.school_id == user.school_id)  # 다른 학교 프로그램 제외 (확장 대비)
    recs = [score_opportunity(user, o, today) for o in db.scalars(query)]
    recs = [r for r in recs if r.score >= TAG_WEIGHT]  # 관심 태그가 하나도 안 겹치면 제외 (가산점만으로는 10점 미만)
    recs.sort(key=lambda r: (-r.score, sort_key(r.opportunity)))
    return recs[:limit]


def latest(db: Session, user: User, scope: str, limit: int = 5) -> list[Recommendation]:
    """관심 분야가 겹치는 글이 없을 때 대신 보여 줄 '최근 글'.
    지원 가능한 글(마감 전, 또는 게시 60일 이내)을 먼저, 그것도 없으면 가장 최근에 올라온 글을 보여 줌."""
    today = date.today()
    query = select(Opportunity).where(Opportunity.scope == scope)
    open_items = sorted(db.scalars(query.where(open_clause(today))), key=sort_key)
    if open_items:
        return [Recommendation(o, score_opportunity(user, o, today).score, ["최근 공고"]) for o in open_items[:limit]]
    old = db.scalars(query.order_by(Opportunity.posted_at.is_(None), Opportunity.posted_at.desc()).limit(limit)).all()
    return [Recommendation(o, 0, ["최근 공고 · 오래된 글이니 원문에서 모집 여부 확인"]) for o in old]


@dataclass
class GapItem:
    spec_name: str
    level: str               # 필수 / 우대
    status: str              # 충족 / 부족 / 없음
    detail: str
    fillers: list[Opportunity] = field(default_factory=list)  # 이 스펙을 채워 줄 활동


@dataclass
class GapResult:
    job: Job
    items: list[GapItem]
    required_total: int
    required_met: int
    preferred_total: int
    preferred_met: int

    @property
    def required_rate(self) -> int:
        return round(self.required_met / self.required_total * 100) if self.required_total else 100


def analyze_gap(db: Session, user: User, job: Job) -> GapResult:
    today = date.today()
    owned = {us.spec_id: us.value for us in user.specs}  # {스펙id: 점수}
    items = []
    for req in job.requirements:
        if req.spec_id not in owned:
            status, detail = "없음", "보유하지 않음"
        elif req.min_value is not None:
            value = owned[req.spec_id]
            if value is not None and value >= req.min_value:
                status, detail = "충족", f"{value:g}점 / 기준 {req.min_value:g}점"
            else:
                shown = "점수 미입력" if value is None else f"{value:g}점"
                status, detail = "부족", f"{shown} / 기준 {req.min_value:g}점"
        else:
            status, detail = "충족", "보유"

        fillers = []
        if status != "충족":
            # 이 스펙을 얻게 해 주는 활동 찾기 (교내 우선, 마감 빠른 순)
            fillers = [o for o in db.scalars(select(Opportunity).where(open_clause(today)))
                       if req.spec_id in {s.id for s in o.specs}]
            fillers.sort(key=lambda o: (o.scope != "교내", sort_key(o)))
            fillers = fillers[:3]
        items.append(GapItem(req.spec.name, req.level, status, detail, fillers))

    items.sort(key=lambda i: (i.level != "필수", i.status == "충족"))  # 필수·미충족을 위로
    req_items = [i for i in items if i.level == "필수"]
    pref_items = [i for i in items if i.level == "우대"]
    return GapResult(
        job=job, items=items,
        required_total=len(req_items), required_met=sum(i.status == "충족" for i in req_items),
        preferred_total=len(pref_items), preferred_met=sum(i.status == "충족" for i in pref_items),
    )

# [AI를 붙일 수 있는 지점]
# 1) 공고 본문 -> 태그 자동 추출 (지금은 seed.py에서 사람이 붙임)
# 2) 채용공고 원문 -> job_requirements 자동 생성
# 3) GapResult -> "다음 학기 추천 계획" 문장 생성
# 4) 후기 여러 개 -> 한 줄 요약
