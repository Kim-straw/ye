"""채용공고 API 가져오기 점검. 실제 API 대신, 비공식 자료로 추정한 응답 모양의 가짜 JSON을 씀.
(실제 응답으로 확인되면 이 FIXTURE를 실제 응답으로 바꿔야 함)"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import job_import, seed
from app.db import Job, Opportunity, SessionLocal
from app.main import app
from tests.helpers import dept_id

END = (date.today() + timedelta(days=9)).strftime("%Y%m%d")
FIXTURE = {"result": [
    {"recrutPblntSn": 1001, "instNm": "가상기관A", "recrutPbancTtl": "2027 전산직 신입 채용", "ncsCdNmLst": "정보통신",
     "aplyQlfcCn": "정보처리기사 자격 보유자", "prefCondCn": "토익 700점 이상, 한국사능력검정 취득자",
     "srcUrl": "https://example.org/job/1001", "pbancEndYmd": END},
    {"recrutPblntSn": 1002, "instNm": "가상기관B", "recrutPbancTtl": "사무직 신입 채용",
     "aplyQlfcCn": "학력 제한 없음", "prefCondCn": ".", "pbancEndYmd": END},  # 스펙 단어 없음 -> 제외
    {"recrutPblntSn": 1003, "instNm": "가상기관C", "recrutPbancTtl": "행정직 체험형 인턴",
     "aplyQlfcCn": "TOEIC 800", "prefCondCn": "봉사활동 경험자 우대", "pbancEndYmd": END},
]}


def fresh():
    seed.run()
    db = SessionLocal()
    records = job_import.find_records({"response": {"body": {"items": FIXTURE["result"]}}})  # 응답이 깊이 감싸져도 찾아야 함
    return db, records


def test_find_and_extract():
    _, records = fresh()
    assert len(records) == 3
    reqs = {n: (lv, ms) for n, lv, ms in job_import.extract_requirements("정보처리기사 자격 보유자", "토익 700점 이상, 한국사능력검정")}
    assert reqs["정보처리기사"] == ("필수", None)
    assert reqs["TOEIC"] == ("우대", 700.0)
    assert reqs["한국사능력검정 1급"] == ("우대", None)
    assert job_import.parse_ymd("2026-11-30") == date(2026, 11, 30) and job_import.parse_ymd("-") is None


def test_save_skip_and_no_duplicates():
    db, records = fresh()
    assert job_import.save_jobs(db, records) == (2, 0, 1)
    assert job_import.save_jobs(db, records) == (0, 2, 1)
    jobs = db.scalars(select(Job).where(Job.is_sample.is_(False))).all()
    assert {j.source_url for j in jobs} == {"https://example.org/job/1001", ""}
    db.close()


def test_error_message():
    err = {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "APPLICATION_ERROR", "returnReasonCode": "01"}}}
    with pytest.raises(RuntimeError, match="APPLICATION_ERROR"):
        job_import.raise_if_error(err)


def test_gap_with_real_job():
    db, records = fresh()
    job_import.save_jobs(db, records)
    db.close()
    client = TestClient(app)
    r = client.post("/profile", data={"nickname": "잡", "department_id": dept_id("컴퓨터소프트웨어학과"), "grade": 3, "admission_year": 2024,
                                      "spec_ids": ["6"], "score_6": "650"}, follow_redirects=False)  # TOEIC 650
    client.cookies.set("user_id", r.cookies["user_id"])

    jobs = client.get("/api/jobs").json()
    assert jobs and all(not j["is_sample"] for j in jobs)  # 실제 공고가 있으면 샘플 직무는 숨김
    assert "가상기관A" in client.get("/jobs").text

    job_a = next(j for j in jobs if "가상기관A" in j["name"])
    gap = client.get(f"/api/gap/{job_a['id']}").json()
    status = {i["spec"]: (i["level"], i["status"]) for i in gap["items"]}
    assert status["정보처리기사"] == ("필수", "없음") and status["TOEIC"] == ("우대", "부족")
    page = client.get(f"/gap/{job_a['id']}").text
    assert "실제 공고" in page and "https://example.org/job/1001" in page


def test_run_from_file(tmp_path, capsys):
    seed.run()
    path = tmp_path / "x.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
    job_import.run(file=str(path))
    out = capsys.readouterr().out
    assert "대외활동 3개" in out and "직무 요건 2개" in out
    db = SessionLocal()
    rows = db.scalars(select(Opportunity).where(Opportunity.source == "api")).all()
    assert len(rows) == 3 and all(r.scope == "외부" and r.deadline for r in rows)
    assert {r.category for r in rows} == {"공공기관 인턴", "공공기관 채용"}
    db.close()
    job_import.run(file=str(path))
    assert "대외활동 0개" in capsys.readouterr().out  # 두 번 실행해도 중복 없음
