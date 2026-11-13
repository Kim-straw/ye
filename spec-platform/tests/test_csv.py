"""직접 입력(CSV) 가져오기 점검. 아래 프로그램 이름은 형식을 시험하려고 지어낸 것이고 실제 프로그램이 아님."""
from datetime import date, timedelta

from sqlalchemy import select

from app import csv_import, seed
from app.db import Opportunity, SessionLocal

HEADER = "제목,주관,분류,구분,마감일,소요시간,난이도,링크,설명,태그\n"
SOON = (date.today() + timedelta(days=20)).isoformat()
CSV = HEADER + (
    f"시험용 데이터 특강,시험센터,특강,교내,{SOON},20,3,https://example.org/a,데이터 분석 기초,데이터;AI\n"
    "시험용 외부 공모전,시험기관,공모전,외부,,,,https://example.org/b,마케팅 아이디어 공모,\n"
    "날짜 오류 프로그램,시험센터,특강,교내,2026-13-45,,,,,\n"
    "구분 오류 프로그램,시험센터,특강,해외,,,,,,\n"
    ",,,,,,,,,\n"
)


def test_import_and_validation(tmp_path):
    seed.run()
    path = tmp_path / "p.csv"
    path.write_text(CSV, encoding="utf-8-sig")
    db = SessionLocal()
    added, dup, problems = csv_import.save_rows(db, csv_import.read_rows(path))
    assert (added, dup) == (2, 0)
    assert len(problems) == 2 and "4번 줄" in problems[0] and "5번 줄" in problems[1]

    a = db.scalars(select(Opportunity).where(Opportunity.title == "시험용 데이터 특강")).one()
    assert a.scope == "교내" and a.source == "manual" and not a.is_sample and a.school_id is not None
    assert str(a.deadline) == SOON and a.hours == 20 and a.difficulty == 3
    assert {t.name for t in a.tags} == {"데이터", "AI"}

    b = db.scalars(select(Opportunity).where(Opportunity.title == "시험용 외부 공모전")).one()
    assert b.scope == "외부" and b.school_id is None and b.deadline is None and b.posted_at == date.today()
    assert "마케팅" in {t.name for t in b.tags}  # 태그를 비우면 설명 키워드로 추정
    assert "공모전 수상" in {s.name for s in b.specs}

    assert csv_import.save_rows(db, csv_import.read_rows(path))[:2] == (0, 2)  # 두 번 넣어도 중복 없음
    db.close()


def test_cp949_and_missing_title_column(tmp_path):
    p = tmp_path / "e.csv"
    p.write_bytes((HEADER + "한글 인코딩 시험,센터,특강,,,,,,,\n").encode("cp949"))  # 옛 엑셀 CSV
    assert csv_import.read_rows(p)[0]["제목"] == "한글 인코딩 시험"
    bad = tmp_path / "bad.csv"
    bad.write_text("이름,주관\nx,y\n", encoding="utf-8")
    try:
        csv_import.read_rows(bad)
        assert False, "제목 칸이 없으면 오류여야 함"
    except ValueError as e:
        assert "제목" in str(e)
