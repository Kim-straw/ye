"""테스트 공용 도우미"""
from sqlalchemy import select

from app.db import Department, SessionLocal, Tag


def dept_id(name: str) -> int:
    db = SessionLocal()
    value = db.scalars(select(Department.id).where(Department.name == name)).one()
    db.close()
    return value


def tag_id(name: str) -> int:
    db = SessionLocal()
    value = db.scalars(select(Tag.id).where(Tag.name == name)).one()
    db.close()
    return value
