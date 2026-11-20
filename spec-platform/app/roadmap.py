"""로드맵 계산: 원본 목록(roadmap_data.py) + 사용자가 바꾼 기록(roadmap_entries 테이블) = 한 사람만의 로드맵.

비유: 원본 목록은 '모두에게 같은 학년별 안내서', 테이블은 '내가 안내서에 한 표시(체크·빼기)와 직접 끼워 넣은 쪽지'.
화면에 보일 때마다 둘을 겹쳐서 내 로드맵을 만듭니다. 안내서를 고치면(배포) 모든 사람에게 바로 반영됩니다.
모든 조회·변경은 user_id로 걸러서, 다른 사람의 기록은 읽지도 바꾸지도 못합니다.
"""
import secrets
from dataclasses import dataclass, field

from sqlalchemy import select

from . import roadmap_data as data
from .db import RoadmapEntry, User
from .seed import DEPARTMENTS, TAGS

# 학과별 분야를 seed.py에 적은 순서 그대로 (첫 번째가 그 학과의 대표 분야)
DEPT_TAG_ORDER = {name: tags for _college, name, tags in DEPARTMENTS}

CUSTOM_PREFIX = "custom:"
TEXT_MAX = 60
MAX_CUSTOM = 20


class NotFound(Exception):
    """없는 항목이거나 다른 사람의 항목"""


@dataclass
class Item:
    key: str
    title: str
    done: bool = False
    custom: bool = False

    @property
    def anchor(self) -> str:  # 화면에서 이 줄로 돌아올 때 쓰는 이름 (주소의 # 뒤)
        return "item-" + self.key.replace(":", "-")


@dataclass
class Plan:
    grade: int
    tags: list[str]
    items: list[Item] = field(default_factory=list)    # 보이는 항목 (원본 + 직접 넣은 것)
    hidden: list[Item] = field(default_factory=list)   # 뺀 원본 항목
    result: str = ""

    @property
    def done(self) -> int:
        return sum(i.done for i in self.items)

    @property
    def total(self) -> int:
        return len(self.items)


def grade_of(user: User) -> int:
    """5·6학년은 4학년 항목을 씀"""
    return min(max(user.grade or 1, 1), 4)


def tag_names(user: User) -> list[str]:
    """학과 기본 분야를 먼저(학과 목록에 적힌 순서, 첫째가 대표 분야), 그다음 내가 고른 관심 분야(seed.TAGS 순서)"""
    order = {name: i for i, name in enumerate(TAGS)}
    listed = DEPT_TAG_ORDER.get(user.department.name, [])
    dept_set = {t.name for t in user.department.tags}
    dept = [n for n in listed if n in dept_set] + sorted(dept_set - set(listed), key=lambda n: order.get(n, 99))
    mine = sorted({t.name for t in user.tags} - set(dept), key=lambda n: order.get(n, 99))
    return dept + mine


def source_items(user: User) -> list[tuple[str, str]]:
    g = grade_of(user)
    items = list(data.COMMON[g])
    for tag in tag_names(user):
        items += data.BY_TAG.get(tag, {}).get(g, [])
    return items


def result_for(user: User) -> str:
    g = grade_of(user)
    for tag in tag_names(user):
        if tag in data.RESULT_BY_TAG:
            return data.RESULT_BY_TAG[tag][g]
    return data.RESULT_BY_GRADE[g]


def _entries(db, user: User) -> dict[str, RoadmapEntry]:
    return {e.item_key: e for e in db.scalars(select(RoadmapEntry).where(RoadmapEntry.user_id == user.id))}


def plan_for(db, user: User) -> Plan:
    entries = _entries(db, user)
    plan = Plan(grade=grade_of(user), tags=tag_names(user), result=result_for(user))
    for key, title in source_items(user):
        e = entries.get(key)
        item = Item(key, title, done=bool(e and e.done))
        (plan.hidden if e and e.hidden else plan.items).append(item)
    customs = sorted((e for e in entries.values() if e.item_key.startswith(CUSTOM_PREFIX)), key=lambda e: e.id)
    plan.items += [Item(e.item_key, e.text or "", done=e.done, custom=True) for e in customs]
    return plan


# ---------- 바꾸기 (모두 내 기록만) ----------
def _mine(db, user: User, key: str) -> RoadmapEntry | None:
    return db.scalars(select(RoadmapEntry).where(RoadmapEntry.user_id == user.id, RoadmapEntry.item_key == key)).first()


def _source_entry(db, user: User, key: str) -> RoadmapEntry:
    """원본 항목의 기록을 꺼내고, 없으면 새로 만듦. 원본 목록에 없는 key는 거절"""
    if key not in data.ALL_ITEMS:
        raise NotFound(key)
    e = _mine(db, user, key)
    if e is None:
        e = RoadmapEntry(user_id=user.id, item_key=key, done=False, hidden=False)
        db.add(e)
    return e


def _tidy(db, e: RoadmapEntry):
    """원본 항목이 '체크 안 함·빼지 않음'으로 돌아오면 저장할 것이 없으니 줄을 지움 (테이블을 작게 유지)"""
    if not e.item_key.startswith(CUSTOM_PREFIX) and not e.done and not e.hidden:
        db.delete(e)


def toggle(db, user: User, key: str) -> Item:
    if key.startswith(CUSTOM_PREFIX):
        e = _mine(db, user, key)
        if e is None:
            raise NotFound(key)
    else:
        e = _source_entry(db, user, key)
    e.done = not e.done
    _tidy(db, e)
    db.commit()
    return Item(key, "")


def set_hidden(db, user: User, key: str, hidden: bool):
    e = _source_entry(db, user, key)  # 직접 넣은 항목은 빼기 대신 삭제
    e.hidden = hidden
    _tidy(db, e)
    db.commit()


def custom_error(db, user: User, text: str) -> str | None:
    if not text:
        return "추가할 내용을 적어 주세요"
    if len(text) > TEXT_MAX:
        return f"{TEXT_MAX}자 이내로 적어 주세요"
    count = sum(1 for k in _entries(db, user) if k.startswith(CUSTOM_PREFIX))
    if count >= MAX_CUSTOM:
        return f"직접 넣은 항목은 {MAX_CUSTOM}개까지예요"
    return None


def add_custom(db, user: User, text: str) -> Item:
    key = CUSTOM_PREFIX + secrets.token_hex(8)
    db.add(RoadmapEntry(user_id=user.id, item_key=key, text=text, done=False, hidden=False))
    db.commit()
    return Item(key, text, custom=True)


def delete_custom(db, user: User, key: str):
    e = _mine(db, user, key) if key.startswith(CUSTOM_PREFIX) else None
    if e is None:
        raise NotFound(key)
    db.delete(e)
    db.commit()
