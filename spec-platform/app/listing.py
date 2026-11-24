"""목록 화면(대외활동·교내 프로그램·인턴·채용) 공통 규칙: 검색·기간·지역 거르기, 정렬, 20개씩 쪽 나누기.

비유: 도서관 검색대. 어떤 서가(교내/대외/채용)에서 꺼낸 책 묶음이든 같은 검색대에 올려
'제목에 이 말이 있는 것만 → 기한 안에 있는 것만 → 이 지역만 → 순서대로 → 20권씩 한 장'으로 정리합니다.
화면·주소(URL)는 모르고, 목록을 받아 목록을 돌려줍니다.
"""
from dataclasses import dataclass
from datetime import date

from . import logic
from .db import Opportunity

PER_PAGE = 20

# (주소 값, 화면 글자). 첫 칸이 기본값
PERIODS = [("", "전체"), ("7", "7일 이내 마감"), ("14", "14일 이내 마감"), ("30", "30일 이내 마감"), ("none", "마감일 없음")]
SORTS = [("", "마감 임박순"), ("new", "최신순")]  # 기본(값 없음)은 예전과 같은 순서: 마감 빠른 순, 마감일 없는 글은 뒤(최신 먼저)


def clean(values) -> list[str]:
    """주소에서 여러 번 온 값(?category=a&category=b): 빈 값과 중복을 빼고 순서 유지"""
    return list(dict.fromkeys(v.strip() for v in (values or []) if v and v.strip()))


def norm_period(value: str) -> str:
    return value if value in {k for k, _ in PERIODS} else ""


def norm_sort(value: str) -> str:
    return value if value in {k for k, _ in SORTS} else ""


def parse_page(raw) -> int:
    """쪽 번호: 숫자가 아니거나 1보다 작으면 1"""
    try:
        return max(int(str(raw).strip()), 1)
    except ValueError:
        return 1


def in_period(o: Opportunity, period: str, today: date) -> bool:
    if not period:
        return True
    if period == "none":
        return o.deadline is None
    return o.deadline is not None and 0 <= (o.deadline - today).days <= int(period)


def search(items: list[Opportunity], q: str) -> list[Opportunity]:
    """제목·기관·본문에 검색어가 들어간 것 (대소문자 구분 없음)"""
    words = q.strip().lower()
    if not words:
        return items
    return [o for o in items if words in f"{o.title} {o.host} {o.description}".lower()]


def narrow(items: list[Opportunity], *, q: str = "", period: str = "", regions: list[str] | None = None,
           today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    items = [o for o in search(items, q) if in_period(o, period, today)]
    if regions:
        items = [o for o in items if logic.recruit_region(o) in regions]
    return items


def sort_items(items: list[Opportunity], sort: str) -> list[Opportunity]:
    if sort == "new":  # 최근 올라온 순, 날짜가 같으면 나중에 넣은 것 먼저
        return sorted(items, key=lambda o: (o.posted_at is None, -(o.posted_at.toordinal() if o.posted_at else 0), -o.id))
    return sorted(items, key=logic.sort_key)


@dataclass
class Page:
    items: list
    page: int      # 지금 쪽 (1부터)
    pages: int     # 전체 쪽 수 (목록이 비어도 1)
    total: int     # 전체 개수

    @property
    def window(self) -> list[int]:
        """쪽 번호 줄에 보여 줄 번호: 지금 쪽 앞뒤로 2개씩, 최대 5개"""
        start = max(1, min(self.page - 2, self.pages - 4))
        return list(range(start, min(start + 5, self.pages + 1)))


def paginate(items: list, page: int, per: int = PER_PAGE) -> Page:
    """범위를 넘은 쪽 번호는 마지막 쪽으로"""
    pages = max(1, -(-len(items) // per))
    page = min(max(page, 1), pages)
    return Page(items[(page - 1) * per: page * per], page, pages, len(items))


def hidden_fields(current: dict, drop: tuple = ()) -> list[tuple[str, str]]:
    """폼에 숨겨서 같이 보낼 지금 조건들 (검색창을 쓰면 필터가, 필터를 쓰면 검색어가 그대로 남게)"""
    out = []
    for k, v in current.items():
        if k in drop:
            continue
        for one in (v if isinstance(v, list) else [v]):
            if one:
                out.append((k, one))
    return out
