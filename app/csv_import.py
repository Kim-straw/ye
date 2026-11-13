"""직접 정리한 프로그램 목록(CSV 파일) -> 교내 프로그램 / 대외활동으로 저장.

로그인이 필요해서 자동으로 가져올 수 없는 곳(포털, 비교과 시스템 등)의 프로그램을
사람이 보고 엑셀에 적은 뒤 앱에 넣을 때 씁니다. (자동 수집은 학교 허락 범위를 넘을 수 있어 하지 않음)

엑셀에서 "다른 이름으로 저장 -> CSV UTF-8(쉼표로 분리)"로 저장하세요.
첫 줄(칸 이름)은 아래 이름 그대로여야 하고, 순서는 상관없습니다. '제목'만 필수입니다.
    제목, 주관, 분류, 구분, 마감일, 소요시간, 난이도, 링크, 설명, 태그
  - 구분: 교내 또는 외부 (비우면 교내)
  - 마감일: 2026-12-15 처럼 (비우면 '오늘 등록'으로 보고 60일간 노출)
  - 소요시간: 숫자(시간), 난이도: 1~5, 모르면 비움
  - 태그: 개발, 데이터 처럼 쉼표나 ; 로 구분. 비우면 제목·설명의 키워드로 추정
실행: python -m app.csv_import 파일이름.csv
"""
import csv
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from .db import Opportunity, School, SessionLocal, Spec, Tag, init_db
from .rss_import import SPEC_KEYWORDS, TAG_KEYWORDS, guess

REQUIRED = ["제목"]


def read_rows(path: Path) -> list[dict]:
    """엑셀이 저장한 CSV는 UTF-8(BOM) 또는 CP949일 수 있어 둘 다 시도"""
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("파일 인코딩을 읽지 못했습니다. 엑셀에서 'CSV UTF-8'로 다시 저장해 주세요.")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or any(c not in [f.strip() for f in reader.fieldnames] for c in REQUIRED):
        raise ValueError(f"첫 줄에 '{REQUIRED[0]}' 칸이 있어야 합니다. 현재 첫 줄: {reader.fieldnames}")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def parse_day(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"마감일 형식을 읽지 못했습니다: '{text}' (예: 2026-12-15)")


def parse_int(text: str, name: str, low: int, high: int) -> int | None:
    if not text:
        return None
    try:
        value = int(float(text))
    except ValueError:
        raise ValueError(f"{name}은 숫자여야 합니다: '{text}'")
    if not low <= value <= high:
        raise ValueError(f"{name}은 {low}~{high} 사이여야 합니다: {value}")
    return value


def save_rows(db, rows: list[dict]) -> tuple[int, int, list[str]]:
    """(새로 저장, 이미 있음, 문제가 있어 건너뛴 줄 설명 목록)"""
    school = db.scalars(select(School)).first()
    tags = {t.name: t for t in db.scalars(select(Tag))}
    specs = {s.name: s for s in db.scalars(select(Spec))}
    known_url = set(db.scalars(select(Opportunity.url).where(Opportunity.url != "")))
    known_title = {(t, h) for t, h in db.execute(select(Opportunity.title, Opportunity.host))}
    added = dup = 0
    problems: list[str] = []
    for line_no, row in enumerate(rows, start=2):  # 엑셀 줄 번호(1번 줄은 칸 이름)
        title = row.get("제목", "")
        if not title:
            if any(row.values()):
                problems.append(f"{line_no}번 줄: 제목이 비어 있어 건너뜀")
            continue
        try:
            scope = row.get("구분") or "교내"
            if scope not in ("교내", "외부"):
                raise ValueError(f"구분은 '교내' 또는 '외부'여야 합니다: '{scope}'")
            deadline = parse_day(row.get("마감일", ""))
            hours = parse_int(row.get("소요시간", ""), "소요시간", 0, 2000)
            difficulty = parse_int(row.get("난이도", ""), "난이도", 1, 5)
        except ValueError as e:
            problems.append(f"{line_no}번 줄 ({title[:20]}): {e}")
            continue
        url, host = row.get("링크", ""), row.get("주관", "")
        if (url and url in known_url) or (title, host) in known_title:
            dup += 1
            continue
        desc = row.get("설명", "")
        text = f"{title} {desc}"
        explicit = [t.strip() for t in row.get("태그", "").replace(";", ",").split(",") if t.strip()]
        tag_names = [t for t in explicit if t in tags] if explicit else guess(text, TAG_KEYWORDS)
        if explicit and len(tag_names) < len(explicit):
            problems.append(f"{line_no}번 줄 ({title[:20]}): 없는 태그는 무시함 -> {[t for t in explicit if t not in tags]}")
        db.add(Opportunity(
            school_id=school.id if (school and scope == "교내") else None, scope=scope,
            category=row.get("분류") or "기타", title=title, host=host or "직접 등록", description=desc,
            difficulty=difficulty, hours=hours, deadline=deadline,
            posted_at=date.today() if deadline is None else None,  # 마감일이 없으면 오늘 등록한 것으로 보고 60일간 노출
            url=url[:300], source="manual", is_sample=False,
            tags=[tags[n] for n in tag_names if n in tags],
            specs=[specs[n] for n in guess(text, SPEC_KEYWORDS) if n in specs],
        ))
        known_url.add(url)
        known_title.add((title, host))
        added += 1
    db.commit()
    return added, dup, problems


def run(path: str) -> None:
    file = Path(path)
    if not file.exists():
        raise SystemExit(f"[오류] 파일을 찾을 수 없습니다: {file.resolve()}")
    init_db()
    try:
        rows = read_rows(file)
    except ValueError as e:
        raise SystemExit(f"[오류] {e}")
    db = SessionLocal()
    added, dup, problems = save_rows(db, rows)
    db.close()
    print(f"[완료] {len(rows)}줄 중 새 프로그램 {added}개 저장 (이미 있음 {dup}, 문제 {len(problems)})")
    for p in problems:
        print("  -", p)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python -m app.csv_import 파일이름.csv")
    run(sys.argv[1])
