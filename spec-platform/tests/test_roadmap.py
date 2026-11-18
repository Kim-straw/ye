"""로드맵: 원본 목록 규칙, 학년·분야별 항목, 체크·빼기·직접 넣기, 남의 항목 보호, 삭제 연동, 새 테이블 생성"""
import re

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app import roadmap_data as data
from app import seed
from app.db import RoadmapEntry, SessionLocal, User, engine
from app.main import app
from tests.helpers import dept_id, tag_id


def test_source_list_rules():
    keys = [k for items in list(data.COMMON.values()) + list(data.BY_TAG.values()) for k, _ in items]
    assert len(keys) == len(set(keys))                                  # key가 겹치지 않음
    assert all(re.fullmatch(r"[a-z0-9_]{3,40}", k) for k in keys)       # key는 영문 소문자·숫자·밑줄
    assert all(len(t) <= 40 for t in data.ALL_ITEMS.values())           # 문장은 40자 이내
    assert set(data.COMMON) == {1, 2, 3, 4} and all(4 <= len(v) <= 6 for v in data.COMMON.values())
    assert set(data.BY_TAG) == set(seed.TAGS) == set(data.RESULT_BY_TAG)  # 21개 분야 모두 있음
    assert all(1 <= len(v) <= 2 for v in data.BY_TAG.values())
    # 사실처럼 보이는 숫자 정보(점수·날짜·퍼센트)를 넣지 않음
    for t in list(data.ALL_ITEMS.values()) + list(data.RESULT_BY_TAG.values()) + list(data.RESULT_BY_GRADE.values()):
        assert not re.search(r"\d{3,}|\d+\s*(점|월|일|%|년)", t), t
