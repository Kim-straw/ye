"""주방 레시피: 추천 점수와 갭 분석. AI 없이 규칙(if, 덧셈)만 씁니다.

DB에서 꺼낸 재료(User, Opportunity, Job)를 받아 계산 결과만 돌려줍니다.
화면이나 주소(URL)는 모릅니다. 그래서 나중에 앱/웹 어디서든 재사용할 수 있습니다.
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Job, Opportunity, User

TAG_WEIGHT = 10        # 겹치는 태그 1개당 점수
ON_CAMPUS_BONUS = 5    # 교내 프로그램 가산점 (핵심 가치: 교내 정보 접근성)
URGENT_BONUS = 3       # 마감 임박 가산점
URGENT_DAYS = 14


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
    days_left = (opp.deadline - today).days
    if 0 <= days_left <= URGENT_DAYS:
        score += URGENT_BONUS
        reasons.append(f"마감 {days_left}일 전")
    return Recommendation(opp, score, reasons)


def recommend(db: Session, user: User, scope: str | None = None, limit: int = 5) -> list[Recommendation]:
    today = date.today()
    query = select(Opportunity).where(Opportunity.deadline >= today)  # 마감 지난 것 제외
    if scope:
        query = query.where(Opportunity.scope == scope)
    if scope == "교내":
        query = query.where(Opportunity.school_id == user.school_id)  # 다른 학교 프로그램 제외 (확장 대비)
    recs = [score_opportunity(user, o, today) for o in db.scalars(query)]
    recs = [r for r in recs if r.score >= TAG_WEIGHT]  # 관심 태그가 하나도 안 겹치면 제외 (가산점만으로는 10점 미만)
    recs.sort(key=lambda r: (-r.score, r.opportunity.deadline))
    return recs[:limit]


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
            fillers = [o for o in db.scalars(select(Opportunity).where(Opportunity.deadline >= today))
                       if req.spec_id in {s.id for s in o.specs}]
            fillers.sort(key=lambda o: (o.scope != "교내", o.deadline))
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
