"""홀(주문 창구): 주소(URL)별로 무엇을 할지 정합니다.

- 화면 주소(/, /me ...)  : HTML을 만들어 보냄 (사람이 보는 용도)
- /api/... 주소          : JSON 데이터만 보냄 (나중에 다른 앱이 붙을 때, /docs에서 연습용)
실행: uvicorn app.main:app --reload   (spec-platform 폴더에서)
"""
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import logic
from .db import Department, Job, Opportunity, Review, School, Spec, Tag, User, UserSpec, get_db, init_db

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 서버가 켜질 때 한 번: 테이블이 없으면 만듦
    yield


app = FastAPI(title="스펙로드 API", description="고려대 세종 스펙·대외활동 통합 플랫폼 (MVP)", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["today"] = date.today

COOKIE = "user_id"  # 손님 번호표 이름


# ---------- 공통: 쿠키 번호표로 현재 사용자 찾기 ----------
def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    raw = request.cookies.get(COOKIE)
    if not raw or not raw.isdigit():
        return None
    return db.get(User, int(raw))


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="프로필을 먼저 만들어 주세요")
    return user


@app.exception_handler(401)
async def to_profile(request: Request, exc):
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": exc.detail}, status_code=401)
    return RedirectResponse("/profile/new", status_code=303)


# ---------- PWA: 폰에 설치하기 위한 파일 (주소가 루트여야 해서 따로 연결) ----------
@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(BASE / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript")


# ================= 화면 (HTML) =================
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: User | None = Depends(current_user)):
    return templates.TemplateResponse(request, "home.html", {"user": user})


@app.get("/profile/new", response_class=HTMLResponse)
def profile_form(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    return templates.TemplateResponse(request, "profile.html", {
        "user": user,
        "departments": db.scalars(select(Department).order_by(Department.college, Department.name)).all(),
        "tags": db.scalars(select(Tag)).all(),
        "specs": db.scalars(select(Spec).order_by(Spec.kind, Spec.id)).all(),
        "owned": {us.spec_id: us.value for us in user.specs} if user else {},
        "my_tags": {t.id for t in user.tags} if user else set(),
    })


@app.post("/profile")
async def save_profile(
    request: Request,
    nickname: str = Form(..., max_length=20),
    department_id: int = Form(...),
    grade: int = Form(..., ge=1, le=6),
    admission_year: int = Form(..., ge=2000, le=2100),
    gpa: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    form = await request.form()  # 체크박스처럼 여러 값이 오는 칸은 직접 꺼냄
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(400, "학과를 다시 선택해 주세요")
    gpa_value = float(gpa) if gpa.strip() else None
    if gpa_value is not None and not (0 <= gpa_value <= 4.5):
        raise HTTPException(400, "학점은 0~4.5 사이로 입력해 주세요")

    if user is None:
        user = User(school_id=dept.school_id, department_id=dept.id, nickname=nickname,
                    grade=grade, admission_year=admission_year, gpa=gpa_value)
        db.add(user)
    else:
        user.school_id, user.department_id = dept.school_id, dept.id
        user.nickname, user.grade, user.admission_year, user.gpa = nickname, grade, admission_year, gpa_value

    tag_ids = [int(t) for t in form.getlist("tag_ids")]
    user.tags = list(db.scalars(select(Tag).where(Tag.id.in_(tag_ids)))) if tag_ids else []

    user.specs.clear()
    db.flush()
    for spec_id in form.getlist("spec_ids"):
        score = str(form.get(f"score_{spec_id}", "")).strip()
        user.specs.append(UserSpec(spec_id=int(spec_id), value=float(score) if score else None))
    db.commit()

    resp = RedirectResponse("/me", status_code=303)  # 303: "저장했으니 이 주소로 다시 가세요"
    resp.set_cookie(COOKIE, str(user.id), max_age=60 * 60 * 24 * 180, httponly=True, samesite="lax")
    return resp


@app.get("/me", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "me.html", {
        "user": user,
        "campus_recs": logic.recommend(db, user, scope="교내"),
        "outside_recs": logic.recommend(db, user, scope="외부"),
    })


@app.get("/opportunities", response_class=HTMLResponse)
def opportunity_list(request: Request, scope: str = "", category: str = "", show_closed: bool = False,
                     db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    query = select(Opportunity)
    if scope:
        query = query.where(Opportunity.scope == scope)
    if category:
        query = query.where(Opportunity.category == category)
    if not show_closed:
        query = query.where(logic.open_clause(date.today()))
    items = sorted(db.scalars(query).all(), key=logic.sort_key)
    categories = sorted(set(db.scalars(select(Opportunity.category))))
    return templates.TemplateResponse(request, "opportunities.html", {
        "user": user, "items": items, "categories": categories,
        "scope": scope, "category": category, "show_closed": show_closed,
    })


@app.get("/opportunities/{opp_id}", response_class=HTMLResponse)
def opportunity_detail(opp_id: int, request: Request, db: Session = Depends(get_db),
                       user: User | None = Depends(current_user)):
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(404, "없는 활동입니다")
    rec = logic.score_opportunity(user, opp) if user else None
    avg = round(sum(r.rating for r in opp.reviews) / len(opp.reviews), 1) if opp.reviews else None
    return templates.TemplateResponse(request, "opportunity.html", {"user": user, "o": opp, "rec": rec, "avg": avg})


@app.post("/opportunities/{opp_id}/reviews")
def write_review(opp_id: int, rating: int = Form(..., ge=1, le=5), content: str = Form(..., min_length=5, max_length=500),
                 db: Session = Depends(get_db), user: User = Depends(require_user)):
    if db.get(Opportunity, opp_id) is None:
        raise HTTPException(404, "없는 활동입니다")
    db.add(Review(opportunity_id=opp_id, user_id=user.id, rating=rating, content=content))
    db.commit()
    return RedirectResponse(f"/opportunities/{opp_id}", status_code=303)


def visible_jobs(db: Session) -> list[Job]:
    """실제 공고(마감 안 지난 것)가 하나라도 있으면 그것만, 없으면 샘플 직무를 보여 줌"""
    today = date.today()
    jobs = db.scalars(select(Job)).all()
    real = [j for j in jobs if not j.is_sample and (j.deadline is None or j.deadline >= today)]
    return real or [j for j in jobs if j.is_sample]


@app.get("/jobs", response_class=HTMLResponse)
def job_list(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    return templates.TemplateResponse(request, "jobs.html", {"user": user, "jobs": visible_jobs(db)})


@app.get("/gap/{job_id}", response_class=HTMLResponse)
def gap_page(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "없는 직무입니다")
    return templates.TemplateResponse(request, "gap.html", {"user": user, "r": logic.analyze_gap(db, user, job)})


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ================= JSON API (/docs 에서 직접 눌러 볼 수 있음) =================
def opp_json(o: Opportunity) -> dict:
    return {"id": o.id, "scope": o.scope, "category": o.category, "title": o.title, "host": o.host,
            "difficulty": o.difficulty, "hours": o.hours,
            "deadline": o.deadline.isoformat() if o.deadline else None,
            "posted_at": o.posted_at.isoformat() if o.posted_at else None,
            "url": o.url, "source": o.source, "tags": [t.name for t in o.tags], "is_sample": o.is_sample}


@app.get("/api/departments", tags=["api"])
def api_departments(db: Session = Depends(get_db)):
    return [{"id": d.id, "college": d.college, "name": d.name} for d in db.scalars(select(Department))]


@app.get("/api/me", tags=["api"])
def api_me(user: User = Depends(require_user)):
    return {"id": user.id, "nickname": user.nickname, "department": user.department.name, "grade": user.grade,
            "tags": [t.name for t in user.tags],
            "specs": [{"name": us.spec.name, "value": us.value} for us in user.specs]}


@app.get("/api/recommendations", tags=["api"])
def api_recommendations(scope: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return [{**opp_json(r.opportunity), "score": r.score, "reasons": r.reasons}
            for r in logic.recommend(db, user, scope=scope)]


@app.get("/api/jobs", tags=["api"])
def api_jobs(db: Session = Depends(get_db)):
    return [{"id": j.id, "name": j.name, "sector": j.sector, "is_sample": j.is_sample,
             "deadline": j.deadline.isoformat() if j.deadline else None, "url": j.source_url}
            for j in visible_jobs(db)]


@app.get("/api/gap/{job_id}", tags=["api"])
def api_gap(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "없는 직무입니다")
    r = logic.analyze_gap(db, user, job)
    return {"job": job.name, "required_rate": r.required_rate,
            "items": [{"spec": i.spec_name, "level": i.level, "status": i.status, "detail": i.detail,
                       "fillers": [opp_json(o) for o in i.fillers]} for i in r.items]}


@app.get("/api/schools", tags=["api"])
def api_schools(db: Session = Depends(get_db)):
    return [{"id": s.id, "name": s.name, "campus": s.campus} for s in db.scalars(select(School))]
