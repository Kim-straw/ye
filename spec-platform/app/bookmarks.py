"""저장한 공고(북마크): 공고 옆 리본 버튼을 누르면 저장, 다시 누르면 해제.

비유: 도서관 책에 꽂는 내 이름표. 이름표는 내 것만 보이고 내 것만 뗄 수 있습니다(모든 조회·변경을 user_id로 거름).
"""
from sqlalchemy import select

from .db import Bookmark, Opportunity, User


def saved_ids(db, user: User | None) -> set[int]:
    if user is None:
        return set()
    return set(db.scalars(select(Bookmark.opportunity_id).where(Bookmark.user_id == user.id)))


def toggle(db, user: User, opp: Opportunity) -> bool:
    """저장돼 있으면 해제, 아니면 저장. 바뀐 뒤 상태(저장됨?)를 돌려줌"""
    row = db.scalars(select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.opportunity_id == opp.id)).first()
    if row:
        db.delete(row)
    else:
        db.add(Bookmark(user_id=user.id, opportunity_id=opp.id))
    db.commit()
    return row is None


def saved_list(db, user: User) -> list[Opportunity]:
    """최근에 저장한 순"""
    rows = db.scalars(select(Bookmark).where(Bookmark.user_id == user.id).order_by(Bookmark.created_at.desc(), Bookmark.id.desc()))
    return [b.opportunity for b in rows]


def safe_next(value: str) -> str:
    """저장 후 돌아갈 주소: 우리 사이트 안의 주소(/로 시작, //·\\로 시작하지 않음)만 허용. 아니면 /saved
    (다른 사이트로 보내는 '열린 리다이렉트'를 막음)"""
    v = (value or "").strip()
    if not v.startswith("/") or v.startswith("//") or "\\" in v or any(ord(ch) < 32 for ch in v):
        return "/saved"
    return v
