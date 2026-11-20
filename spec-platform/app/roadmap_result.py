"""로드맵 결과: 1~4학년 로드맵 + 고른 진로 방향을 한 번에 정리 (화면은 이 결과를 받아 그리기만 함).

진로 방향 선택은 새 칸·테이블 없이 기존 roadmap_entries에 'path:<직군키>' 행으로 저장합니다.
로드맵 계산(roadmap.plan_for)은 'custom:'으로 시작하는 행과 원본 항목 key만 보므로, 'path:' 행은
진행도·직접 넣기 개수(20개)·추천 화면 숫자에 섞이지 않습니다.
"""
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from . import roadmap
from . import roadmap_data as data
from .db import RoadmapEntry, User

PATH_PREFIX = "path:"
MAX_PATHS = 3


@dataclass
class GradeSummary:
    grade: int
    current: bool
    done: list[roadmap.Item] = field(default_factory=list)   # 완료한 것
    todo: list[roadmap.Item] = field(default_factory=list)   # 앞으로 할 것 (뺀 항목 제외, 직접 넣은 항목 포함)

    @property
    def total(self) -> int:
        return len(self.done) + len(self.todo)

    @property
    def percent(self) -> int:  # 타임라인 막대 길이
        return round(len(self.done) / self.total * 100) if self.total else 0


@dataclass
class Result:
    department: str
    grade: int
    tags: list[str]
    grades: list[GradeSummary]
    now: list[roadmap.Item]          # 지금 할 일 (현재 학년에서 아직 안 한 것 앞 3개)
    chosen: list[str]                # 고른 직군 key (PATHS 순서)
    recommended: set[str]            # 내 분야 기준 추천 직군 key
    paths: list[dict]                # 고른 직군의 가이드 (PATHS의 항목 그대로)

    @property
    def done(self) -> int:
        return sum(len(g.done) for g in self.grades)

    @property
    def total(self) -> int:
        return sum(g.total for g in self.grades)


def chosen_paths(db, user: User) -> list[str]:
    keys = set(db.scalars(select(RoadmapEntry.item_key).where(
        RoadmapEntry.user_id == user.id, RoadmapEntry.item_key.startswith(PATH_PREFIX))))
    return [p["key"] for p in data.PATHS if PATH_PREFIX + p["key"] in keys]


def path_error(keys: list[str]) -> str | None:
    if len(set(keys)) > MAX_PATHS:
        return f"진로 방향은 {MAX_PATHS}개까지 고를 수 있어요"
    if any(k not in data.PATH_BY_KEY for k in keys):
        return "없는 진로 방향이에요"
    return None


def save_paths(db, user: User, keys: list[str]):
    """내 'path:' 행만 지우고 새로 저장 (다른 사용자 행은 건드리지 않음). 검사(path_error)는 부르기 전에"""
    db.execute(delete(RoadmapEntry).where(RoadmapEntry.user_id == user.id,
                                          RoadmapEntry.item_key.startswith(PATH_PREFIX)))
    for k in dict.fromkeys(keys):  # 같은 값이 두 번 와도 한 번만
        db.add(RoadmapEntry(user_id=user.id, item_key=PATH_PREFIX + k, text=None, done=False, hidden=False))
    db.commit()


def recommended_paths(user: User) -> set[str]:
    return {k for tag in roadmap.tag_names(user) for k in data.TAG_PATHS.get(tag, [])}


def result_for(db, user: User) -> Result:
    plan = roadmap.plan_for(db, user)
    grades = [GradeSummary(s.grade, s.current, [i for i in s.items if i.done], [i for i in s.items if not i.done])
              for s in plan.sections]
    chosen = chosen_paths(db, user)
    return Result(department=user.department.name, grade=plan.grade, tags=plan.tags, grades=grades,
                  now=grades[plan.grade - 1].todo[:3], chosen=chosen, recommended=recommended_paths(user),
                  paths=[data.PATH_BY_KEY[k] for k in chosen])
