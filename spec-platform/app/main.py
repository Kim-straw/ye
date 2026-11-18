"""홀(주문 창구): 주소(URL)별로 무엇을 할지 정합니다.

- 화면 주소(/, /me ...)  : HTML을 만들어 보냄 (사람이 보는 용도)
- /api/... 주소          : JSON 데이터만 보냄 (나중에 다른 앱이 붙을 때, /docs에서 연습용)
실행: uvicorn app.main:app --reload   (spec-platform 폴더에서)
"""
import os
from urllib.parse import urlencode
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import accounts, logic, rss_import, security, seed
from .db import Department, Job, Opportunity, Review, School, Spec, Tag, User, UserSpec, get_db

BASE = Path(__file__).resolve().parent


def _refresh_loop():
    """백그라운드로 학교 공지를 주기적으로 수집. 실패해도 서버는 계속 동작함."""
    while True:
        try:
            rss_import.run()
        except Exception as e:  # 학교 사이트가 서버의 접속을 막는 경우 등
            print(f"[공지 수집 실패] {e}")
        time.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed.ensure()  # 서버가 켜질 때 한 번: 테이블이 없으면 만들고, DB가 비어 있으면 기본 데이터를 채움 (있으면 건드리지 않음)
    if os.environ.get("AUTO_REFRESH") == "1":  # 서버에서만: 학교 게시판 공지를 6시간마다 다시 가져옴
        threading.Thread(target=_refresh_loop, daemon=True).start()
    yield


app = FastAPI(title="스펙로드 API", description="고려대 세종 스펙·대외활동 통합 플랫폼 (MVP)", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["today"] = date.today
templates.env.globals["display_host"] = logic.display_host

COOKIE = "user_id"  # 손님 번호표 이름


# ---------- 공통: 쿠키 번호표로 현재 사용자 찾기 ----------
def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    # [로그인을 붙일 자리] 지금은 서명된 쿠키 번호표로만 사용자를 찾음. 로그인(비밀번호/학교 메일)을 만들면 여기서 세션을 확인하도록 바꿈.
    user_id = security.verify(request.cookies.get(COOKIE))  # 서명이 안 맞는(위조된) 쿠키는 없는 것으로 취급
    return db.get(User, user_id) if user_id is not None else None


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
@app.get("/healthz", include_in_schema=False)
def healthz():
    """서버가 살아 있는지 확인하는 주소 (Render가 주기적으로 확인함). DB는 건드리지 않음"""
    return {"ok": True}


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(BASE / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript")


def make_link(path: str, current: dict):
    """칩을 누를 때 쓸 주소 만들기: 지금 조건(current)은 그대로 두고 바꾼 값만 덮어씀. 빈 값은 주소에서 뺌.
    예) 지금 ?q=인턴&sector=사기업 에서 link(region="서울") -> ?q=인턴&sector=사기업&region=서울"""
    def link(**change):
        params = {k: v for k, v in {**current, **change}.items() if v}
        return path + ("?" + urlencode(params) if params else "")
    return link


# ================= 화면 (HTML) =================
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    # 홈 화면용: 실제로 가져온 학교 공지·직접 등록 중 최근 것 3개 (게시일이 없는 글은 뒤로)
    recent = db.scalars(select(Opportunity).where(Opportunity.is_sample.is_(False))
                        .order_by(Opportunity.posted_at.is_(None), Opportunity.posted_at.desc(), Opportunity.id.desc())
                        .limit(3)).all()
    return templates.TemplateResponse(request, "home.html", {"user": user, "recent": recent})


def render_profile(request: Request, db: Session, user: User | None, error: str = "", prefill: dict | None = None,
                   account_error: str = "", status: int = 200):
    """프로필 화면. 저장에 실패하면 입력한 값(prefill)을 그대로 채운 채 오류 한 줄과 함께 다시 보여 줌"""
    prefill = prefill or {}
    return templates.TemplateResponse(request, "profile.html", {
        "user": user, "error": error, "account_error": account_error, "pf": prefill,
        "departments": db.scalars(select(Department).order_by(Department.id)).all(),
        "tags": db.scalars(select(Tag)).all(),
        "specs": db.scalars(select(Spec).order_by(Spec.kind, Spec.id)).all(),
        "owned": {us.spec_id: us.value for us in user.specs} if user else {},
        "my_tags": {t.id for t in user.tags} if user else set(prefill.get("tag_ids", [])),
    }, status_code=status)


def login_response(request: Request, user: User, to: str = "/me") -> RedirectResponse:
    """로그인 상태로 만들기: 서명한 번호표 쿠키를 심고 이동 (프로필 저장·로그인이 같이 씀)"""
    resp = RedirectResponse(to, status_code=303)  # 303: "처리했으니 이 주소로 다시 가세요"
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"  # 인터넷(https)에서는 https로만 쿠키를 보냄
    resp.set_cookie(COOKIE, security.sign(user.id), max_age=60 * 60 * 24 * 180, httponly=True, samesite="lax", secure=https)
    return resp


@app.get("/profile/new", response_class=HTMLResponse)
def profile_form(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    return render_profile(request, db, user)


@app.post("/profile")
async def save_profile(
    request: Request,
    nickname: str = Form(..., max_length=20),
    department_id: int = Form(...),
    grade: int = Form(..., ge=1, le=6),
    admission_year: int = Form(..., ge=2000, le=2100),
    gpa: str = Form(""),
    login_id: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    form = await request.form()  # 체크박스처럼 여러 값이 오는 칸은 직접 꺼냄
    new_login = None
    if user is None and (login_id or password):
        # 새 사용자의 아이디·비밀번호: 화면에서는 필수. 서버는 값이 왔을 때만 검사함
        # (값 없이 오면 예전처럼 쿠키로만 쓰는 프로필이 되어, 기존 API·테스트가 그대로 동작)
        new_login = accounts.normalize_login_id(login_id)
        problem = accounts.account_error(new_login, password, password2)
        if problem is None and db.scalar(select(User.id).where(User.login_id == new_login)) is not None:
            problem = "이미 쓰는 아이디예요"
        if problem:
            prefill = {"nickname": nickname, "department_id": department_id, "grade": grade, "admission_year": admission_year,
                       "gpa": gpa, "login_id": new_login, "tag_ids": {int(t) for t in form.getlist("tag_ids")}}
            return render_profile(request, db, None, error=problem, prefill=prefill, status=400)
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(400, "학과를 다시 선택해 주세요")
    gpa_value = float(gpa) if gpa.strip() else None
    if gpa_value is not None and not (0 <= gpa_value <= 4.5):
        raise HTTPException(400, "학점은 0~4.5 사이로 입력해 주세요")

    if user is None:
        user = User(school_id=dept.school_id, department_id=dept.id, nickname=nickname,
                    grade=grade, admission_year=admission_year, gpa=gpa_value)
        if new_login:
            user.login_id, user.password_hash = new_login, accounts.hash_password(password)
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
    return login_response(request, user)


# ---------- 로그인: 같은 프로필을 다른 기기에서도 다시 열기 ----------
LOGIN_FAIL = "아이디 또는 비밀번호가 맞지 않아요"  # 아이디가 없는지, 비밀번호가 틀렸는지 알려 주지 않음


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user: User | None = Depends(current_user)):
    if user is not None and user.login_id:
        return RedirectResponse("/me", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": user, "error": "", "login_id": ""})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, login_id: str = Form(""), password: str = Form(""), db: Session = Depends(get_db)):
    lid = accounts.normalize_login_id(login_id)
    ip = request.client.host if request.client else "?"
    def fail(msg, status):
        return templates.TemplateResponse(request, "login.html", {"user": None, "error": msg, "login_id": lid}, status_code=status)
    if accounts.limiter.blocked(ip, lid):
        return fail("잠시 후 다시 시도해 주세요", 429)
    found = db.scalars(select(User).where(User.login_id == lid)).first() if lid else None
    if not accounts.check_login(password, found.password_hash if found else None):
        accounts.limiter.fail(ip, lid)
        return fail(LOGIN_FAIL, 401)
    accounts.limiter.reset(ip, lid)
    return login_response(request, found)


@app.post("/account", response_class=HTMLResponse)
def create_account(request: Request, login_id: str = Form(""), password: str = Form(""), password2: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(require_user)):
    """쿠키로만 쓰던 기존 사용자가 아이디·비밀번호를 연결"""
    if user.login_id:
        return render_profile(request, db, user, account_error="이미 로그인 정보가 있어요", status=400)
    lid = accounts.normalize_login_id(login_id)
    problem = accounts.account_error(lid, password, password2)
    if problem is None and db.scalar(select(User.id).where(User.login_id == lid)) is not None:
        problem = "이미 쓰는 아이디예요"
    if problem:
        return render_profile(request, db, user, account_error=problem, prefill={"login_id": lid}, status=400)
    user.login_id, user.password_hash = lid, accounts.hash_password(password)
    db.commit()
    return RedirectResponse("/profile/new?account=1", status_code=303)


@app.get("/me", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    outside_recs = logic.recommend(db, user, scope="외부")
    outside_fallback = not outside_recs  # 관심 분야가 겹치는 대외활동이 없으면 최근 대외활동을 대신 보여 줌
    if outside_fallback:
        outside_recs = logic.latest(db, user, scope="외부")
    return templates.TemplateResponse(request, "me.html", {
        "user": user,
        "campus_recs": logic.recommend(db, user, scope="교내"),
        "outside_recs": outside_recs,
        "outside_fallback": outside_fallback,
        "outside_total": db.scalar(select(func.count(Opportunity.id)).where(Opportunity.scope == "외부")),
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
    link = make_link("/opportunities", {"scope": scope, "category": category, "show_closed": "true" if show_closed else ""})
    return templates.TemplateResponse(request, "opportunities.html", {
        "user": user, "items": items, "categories": categories,
        "scope": scope, "category": category, "show_closed": show_closed, "link": link,
    })


@app.get("/recruit", response_class=HTMLResponse)
def recruit(request: Request, q: str = "", kind: str = "", sector: str = "", region: str = "", mine: bool = False,
            show_closed: bool = False, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    """인턴·채용 칸: 취업·현장실습 공고를 분야·지역 칩으로 걸러 보기"""
    today = date.today()
    items = [o for o in db.scalars(select(Opportunity)).all() if logic.is_recruit(o)]
    if not show_closed:
        items = [o for o in items if logic.is_open(o, today)]
    if kind:  # 화면의 선택 칸은 없앴지만 예전 주소(?kind=...)가 깨지지 않게 남겨 둠
        items = [o for o in items if logic.recruit_kind(o) == kind]
    if sector:
        items = [o for o in items if logic.recruit_sector(o) == sector]
    if region:
        items = [o for o in items if logic.recruit_region(o) == region]
    words = q.strip().lower()
    if words:
        items = [o for o in items if words in f"{o.title} {o.host} {o.description}".lower()]
    if mine and user:
        my = logic.user_tag_ids(user)
        items = [o for o in items if any(t.id in my for t in o.tags)]
    items.sort(key=logic.sort_key)
    my_tags = []
    if user:
        my_tags = list(dict.fromkeys([t.name for t in user.department.tags] + [t.name for t in user.tags]))[:3]
    link = make_link("/recruit", {"q": q, "kind": kind, "sector": sector, "region": region,
                                  "mine": "true" if mine else "", "show_closed": "true" if show_closed else ""})
    return templates.TemplateResponse(request, "recruit.html", {
        "user": user, "items": items, "q": q, "kind": kind, "sector": sector, "region": region, "mine": mine,
        "show_closed": show_closed, "my_tags": my_tags, "link": link,
        "sectors": logic.SECTORS, "regions": logic.REGIONS,
        "sector_of": logic.recruit_sector, "region_of": logic.recruit_region, "kind_of": logic.recruit_kind,
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
    mine = db.scalars(select(Review).where(Review.opportunity_id == opp_id, Review.user_id == user.id)).first()
    if mine:  # 한 사람당 활동 하나에 후기 하나: 다시 쓰면 기존 후기를 고침 (도배 방지)
        mine.rating, mine.content = rating, content
    else:
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


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, user: User | None = Depends(current_user)):
    return templates.TemplateResponse(request, "privacy.html", {"user": user})


@app.post("/profile/delete")
def delete_profile(confirm: str = Form(""), db: Session = Depends(get_db), user: User = Depends(require_user)):
    """내 정보 삭제: 프로필과 내가 쓴 후기를 DB에서 지우고 쿠키도 지움"""
    if confirm != "yes":
        raise HTTPException(400, "삭제 확인란에 체크해 주세요")
    for r in db.scalars(select(Review).where(Review.user_id == user.id)).all():
        db.delete(r)
    db.delete(user)  # 관심 분야 연결과 보유 스펙도 함께 지워짐
    db.commit()
    resp = RedirectResponse("/?deleted=1", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


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
