"""공공기관 채용공고 API -> 직무(jobs) + 자격요건(job_requirements) 저장.

흐름:  API 호출 -> 공고 목록(JSON) -> 공고마다 '지원자격'·'우대조건' 글에서 스펙 단어 찾기 -> DB 저장
- 지원자격 글에서 찾은 스펙 = 필수, 우대조건 글에서 찾은 스펙 = 우대
- 우리 스펙 목록(정보처리기사, TOEIC ...)과 연결되는 단어가 하나도 없는 공고는 저장하지 않음(갭 분석이 불가능)

준비: spec-platform/.env 에 아래 두 줄 (키는 본인 PC에만 둡니다)
    DATA_GO_KR_KEY=Decoding_인증키
    JOB_API_URL=https://apis.data.go.kr/1051000/recruitment/list
실행:
    python -m app.job_import --dump     # 응답 항목 이름만 확인 (DB 변경 없음)
    python -m app.job_import            # 진행 중인 공고를 받아 저장 (기본 최대 3페이지)
    python -m app.job_import --file x.json   # 인터넷 없이 저장해 둔 JSON 파일로 시험

주의: 응답 항목 이름(FIELD)은 비공식 자료로 만들었고 실제 응답으로는 아직 확인하지 못했습니다.
      --dump 결과와 다르면 FIELD 표만 고치면 됩니다.
"""
import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from .db import Job, JobRequirement, SessionLocal, Spec, init_db

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# 우리가 쓰려는 값 -> 응답에서 가능한 항목 이름들 (앞에서부터 찾음)
FIELD = {
    "id": ["recrutPblntSn", "pblntSn", "sn"],
    "org": ["instNm", "pblntInstNm", "insttNm"],
    "title": ["recrutPbancTtl", "pbancTtl", "title"],
    "ncs": ["ncsCdNmLst", "ncsCdLst", "ncsNm"],
    "qual": ["aplyQlfcCn", "aplyQlfc"],        # 지원자격
    "pref": ["prefCondCn", "prefCn", "prefCond"],  # 우대조건
    "url": ["srcUrl", "url", "pbancUrl"],
    "end": ["pbancEndYmd", "endYmd", "rceptEndYmd"],
}

# 글 속 단어 -> 우리 스펙 이름. 앞의 것이 먼저 검사됨.
SPEC_PATTERNS = [
    ("정보처리기사", r"정보처리\s*기사"),
    ("SQLD", r"SQLD|SQL\s*개발자"),
    ("ADsP", r"ADsP|데이터\s*분석\s*준전문가"),
    ("컴퓨터활용능력 1급", r"컴퓨터\s*활용\s*능력"),
    ("한국사능력검정 1급", r"한국사\s*능력\s*검정"),
    ("OPIc IM2 이상", r"OPIc|오픽"),
    ("인턴 경험", r"인턴"),
    ("공모전 수상", r"공모전"),
    ("봉사활동 경험", r"봉사"),
]
TOEIC_RE = re.compile(r"(?:토익|TOEIC)[^0-9]{0,10}(\d{3})", re.IGNORECASE)
TOEIC_WORD = re.compile(r"토익|TOEIC", re.IGNORECASE)

ERROR_HINTS = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": "인증키가 아직 등록되지 않았습니다. 승인 직후라면 1~2시간 뒤 다시 시도하고, Decoding 키를 넣었는지 확인하세요.",
    "SERVICE_ACCESS_DENIED_ERROR": "이 API의 활용신청이 승인되지 않았습니다.",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": "하루 호출 한도(개발계정 1,000건)를 넘었습니다. 내일 다시 시도하세요.",
    "APPLICATION_ERROR": "서버 쪽 오류입니다. 키 반영 대기이거나 제공기관 서버 문제일 수 있습니다. 시간을 두고 다시 시도하세요.",
}


# ---------- .env / API 호출 ----------
def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        raise SystemExit(f"[오류] .env 파일이 없습니다: {ENV_PATH}")
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            env[name.strip()] = value.strip().strip('"').strip("'")
    return env


def fetch_page(url: str, key: str, page: int, rows: int) -> dict:
    params = {"serviceKey": key, "pageNo": page, "numOfRows": rows, "resultType": "json", "ongoingYn": "Y"}
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="")
    try:
        with urllib.request.urlopen(full, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"서버에 연결하지 못했습니다: {e.reason}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("JSON이 아닌 응답이 왔습니다: " + body[:200].replace(key, "***"))
    raise_if_error(data)
    return data


def raise_if_error(data: dict):
    """오류 응답(OpenAPI_ServiceResponse)이면 이해하기 쉬운 문장으로 알려 줌"""
    header = (data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader")
    if header:
        name = header.get("errMsg", "")
        raise RuntimeError(f"API 오류 {name} (코드 {header.get('returnReasonCode', '?')}): "
                           + ERROR_HINTS.get(name, "공공데이터포털 오류 코드표를 확인하세요."))


# ---------- 응답 해석 ----------
def find_records(obj) -> list[dict]:
    """응답 어디에 있든 '공고 목록(딕셔너리 리스트)'을 찾아냄. 공고 제목 항목이 있는 리스트를 우선."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(pick(x, "title") for x in obj):
            return obj
        for x in obj:
            found = find_records(x)
            if found:
                return found
    elif isinstance(obj, dict):
        for v in obj.values():
            found = find_records(v)
            if found:
                return found
    return []


def pick(rec: dict, name: str) -> str:
    """FIELD 표의 후보 이름 중 값이 있는 첫 번째를 글자로 돌려줌. 빈 값(".", "-")은 없는 것으로 취급."""
    for key in FIELD[name]:
        value = rec.get(key)
        if value is not None and str(value).strip() not in ("", ".", "-"):
            return str(value).strip()
    return ""


def parse_ymd(text: str) -> date | None:
    digits = re.sub(r"\D", "", text)[:8]
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None


def extract_requirements(qual: str, pref: str) -> list[tuple[str, str, float | None]]:
    """지원자격·우대조건 글 -> [(스펙 이름, 필수/우대, 최소 점수), ...]"""
    found: dict[str, tuple[str, float | None]] = {}
    for text, level in ((pref, "우대"), (qual, "필수")):  # 필수를 나중에 넣어 같은 스펙이면 필수가 이김
        for name, pattern in SPEC_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                found[name] = (level, None)
        if TOEIC_WORD.search(text):
            m = TOEIC_RE.search(text)
            found["TOEIC"] = (level, float(m.group(1)) if m else None)
    return [(name, level, score) for name, (level, score) in found.items()]


def save_jobs(db, records: list[dict]) -> tuple[int, int, int]:
    """(새로 저장, 이미 있음, 스펙 단어가 없어 건너뜀) 개수를 돌려줌"""
    specs = {s.name: s for s in db.scalars(select(Spec))}
    known = set(db.scalars(select(Job.source_id).where(Job.source_id.is_not(None))))
    added = dup = skipped = 0
    for rec in records:
        sid, title = pick(rec, "id"), pick(rec, "title")
        if not title:
            continue
        sid = sid or f"{pick(rec, 'org')}|{title}"
        if sid in known:
            dup += 1
            continue
        reqs = [r for r in extract_requirements(pick(rec, "qual"), pick(rec, "pref")) if r[0] in specs]
        if not reqs:
            skipped += 1
            continue
        url = pick(rec, "url")
        org = pick(rec, "org")
        db.add(Job(
            name=f"{org} · {title}"[:50], sector="공공기관", is_sample=False, source_id=sid, source_url=url[:300],
            deadline=parse_ymd(pick(rec, "end")), description=("직무: " + pick(rec, "ncs")) if pick(rec, "ncs") else "",
            requirements=[JobRequirement(spec=specs[n], level=lv, min_value=ms, source_url=url[:300]) for n, lv, ms in reqs],
        ))
        known.add(sid)
        added += 1
    db.commit()
    return added, dup, skipped


# ---------- 실행 ----------
def run(max_pages: int = 3, rows: int = 100, file: str | None = None) -> None:
    init_db()
    records: list[dict] = []
    if file:
        records = find_records(json.loads(Path(file).read_text(encoding="utf-8")))
    else:
        env = load_env()
        key, url = env.get("DATA_GO_KR_KEY", ""), env.get("JOB_API_URL", "")
        if not key or not url:
            raise SystemExit("[오류] .env에 DATA_GO_KR_KEY 와 JOB_API_URL 두 줄이 모두 있어야 합니다.")
        for page in range(1, max_pages + 1):
            try:
                got = find_records(fetch_page(url, key, page, rows))
            except RuntimeError as e:
                raise SystemExit(f"[실패] {e}")
            records += got
            if len(got) < rows:
                break
    db = SessionLocal()
    added, dup, skipped = save_jobs(db, records)
    db.close()
    print(f"[완료] 공고 {len(records)}개 중 새 직무 {added}개 저장 (이미 있음 {dup}, 스펙 단어 없어 제외 {skipped})")


def dump() -> None:
    """응답 항목 이름 확인용. DB는 건드리지 않고, 인증키도 출력하지 않음."""
    env = load_env()
    try:
        data = fetch_page(env.get("JOB_API_URL", ""), env.get("DATA_GO_KR_KEY", ""), 1, 1)
    except RuntimeError as e:
        raise SystemExit(f"[실패] {e}")
    recs = find_records(data)
    if not recs:
        print("공고 목록을 찾지 못했습니다. 응답 앞부분:\n" + json.dumps(data, ensure_ascii=False)[:1500])
        return
    print("항목 이름:", list(recs[0].keys()))
    print("첫 공고:\n" + json.dumps(recs[0], ensure_ascii=False, indent=2)[:2500])
    missing = [n for n in FIELD if not pick(recs[0], n)]
    print("\nFIELD 표로 못 읽은 값:", missing or "없음")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--file")
    args = ap.parse_args()
    dump() if args.dump else run(max_pages=args.pages, file=args.file)
