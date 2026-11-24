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

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import accounts, bookmarks, listing, logic, roadmap, roadmap_data, roadmap_result, rss_import, security, seed
from .db import Bookmark, Department, Job, Opportunity, Review, RoadmapEntry, School, Spec, Tag, User, UserSpec, get_db

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
templates.env.globals["monogram"] = logic.monogram

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
    예) 지금 ?q=인턴&sector=사기업 에서 link(region="서울") -> ?q=인턴&sector=사기업&region=서울
    값이 목록이면(?category=a&category=b) 같은 이름으로 여러 번 붙임. page는 따로 주지 않으면 빠짐(조건이 바뀌면 1쪽부터)"""
    def link(**change):
        params = {k: v for k, v in {**current, **change}.items() if v}
        return path + ("?" + urlencode(params, doseq=True) if params else "")
    return link


# 상위 카테고리: (이름, 주소, 이 화면이 해당하는지 판단할 열쇠)
TOP_CATEGORIES = [("전체", "/opportunities", {}, "all"), ("교내", "/opportunities", {"scope": "교내"}, "교내"),
                  ("대외활동", "/opportunities", {"scope": "외부"}, "외부"), ("인턴·채용", "/recruit", {}, "recruit")]


def build_catbar(active: str, show_closed: bool, sub_names: list[str], sub_selected: str, sub_link) -> dict:
    """2단계 카테고리 바에 그릴 내용만 계산 (템플릿은 그리기만 함).
    active: 지금 화면의 상위 열쇠 / sub_names: 하위 이름들(전체 제외) / sub_link: 하위 값 하나만 바꾼 주소를 돌려주는 함수
    - 상위 링크는 show_closed만 가져감 (다른 화면으로 가면 하위 선택은 처음부터)
    - 하위가 0~1개면 '전체'와 똑같은 목록이라 하위 줄을 그리지 않음"""
    keep = {"show_closed": "true"} if show_closed else {}
    top = [{"name": name, "href": make_link(path, {**params, **keep})(), "on": key == active}
           for name, path, params, key in TOP_CATEGORIES]
    sub = []
    if len(sub_names) > 1:
        sub = [{"name": "전체", "href": sub_link(""), "on": not sub_selected}]
        sub += [{"name": n, "href": sub_link(n), "on": n == sub_selected} for n in sub_names]
    return {"top": top, "sub": sub}


# ================= 화면 (HTML) =================
@app.get("/", response_class=HTMLResponse)
def home(request: Request, tab: str = "new", db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    """홈: 소개(로그인 전)·인사(로그인 후) → 바로가기 카드 4개(실제 개수) → 마감 임박(가로로 넘겨 보기) → 탭이 있는 공고 목록"""
    today = date.today()
    real_open = select(Opportunity).where(Opportunity.is_sample.is_(False), logic.open_clause(today))
    # 마감 임박: 마감일이 있는 열린 공고를 마감 가까운 순으로 5개 (규칙은 기존 open_clause·sort_key 그대로)
    urgent = db.scalars(real_open.where(Opportunity.deadline.is_not(None))
                        .order_by(Opportunity.deadline, Opportunity.id).limit(5)).all()
    mine = [r.opportunity for r in logic.recommend(db, user, limit=5)] if user else []
    tabs = [("new", "새 공고"), ("urgent", "마감 임박")] + ([("mine", "내 분야")] if mine else [])
    if tab not in {k for k, _ in tabs}:
        tab = "new"  # 모르는 값이나 쓸 수 없는 탭은 '새 공고'로
    if tab == "new":
        feed = db.scalars(real_open.order_by(Opportunity.posted_at.is_(None), Opportunity.posted_at.desc(),
                                             Opportunity.id.desc()).limit(5)).all()
        more = "/opportunities"
    elif tab == "urgent":  # 위 가로 영역에 이미 나온 공고는 빼고 그다음 마감 순 (같은 공고를 두 번 보여 주지 않게)
        shown = [o.id for o in urgent]
        feed = db.scalars(real_open.where(Opportunity.deadline.is_not(None), Opportunity.id.not_in(shown or [0]))
                          .order_by(Opportunity.deadline, Opportunity.id).limit(5)).all()
        more = "/opportunities"
    else:
        feed, more = mine, "/me"
    # 바로가기 카드의 숫자: 각 목록을 기본 조건(마감 안 지난 것)으로 열었을 때 보이는 개수와 같게
    open_count = lambda scope: db.scalar(select(func.count(Opportunity.id)).where(Opportunity.scope == scope, logic.open_clause(today)))
    plan = roadmap.plan_for(db, user) if user else None
    counts = {
        "roadmap": f"{plan.done}/{plan.total}" if plan else "",
        "외부": open_count("외부"), "교내": open_count("교내"),
        "recruit": sum(1 for o in db.scalars(select(Opportunity)) if logic.is_recruit(o) and logic.is_open(o, today)),
    }
    return templates.TemplateResponse(request, "home.html", {
        "user": user, "urgent": urgent, "tabs": tabs, "tab": tab, "feed": feed, "more": more,
        "counts": counts, "plan": plan, "stages": roadmap.STAGES,
    })


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
        "user": user, "rm": roadmap.plan_for(db, user),
        "campus_recs": logic.recommend(db, user, scope="교내"),
        "outside_recs": outside_recs,
        "outside_fallback": outside_fallback,
        "outside_total": db.scalar(select(func.count(Opportunity.id)).where(Opportunity.scope == "외부")),
    })


# ---------- 로드맵: 1~4학년 안내 + 내가 넣고 뺀 것 = 한 사람만의 로드맵 ----------
def opened_grades(user: User, open_: str) -> set[int]:
    """펼쳐 둘 학년 구역: 내 현재 학년 + 주소의 open 값(1~4 하나 또는 all)"""
    current = roadmap.grade_of(user)
    if open_ == "all":
        return set(roadmap.GRADES)
    g = roadmap.parse_grade(open_) if open_ else None
    return {current} | ({g} if g else set())


def render_roadmap(request: Request, db: Session, user: User, open_: str = "", error: str = "", draft: str = "",
                   draft_grade: int | None = None, status: int = 200):
    plan = roadmap.plan_for(db, user)
    side = "all" if open_ == "all" else (roadmap.parse_grade(open_) or plan.grade)  # 왼쪽 메뉴에서 선택 표시할 칸
    return templates.TemplateResponse(request, "roadmap.html", {
        "user": user, "plan": plan, "opened": opened_grades(user, open_), "all_open": open_ == "all",
        "side": side, "stages": roadmap.STAGES,
        # 추가 칸의 학년 기본값: 오류로 다시 그릴 때는 고른 학년, 아니면 지금 열어서 작업 중인 학년(open), 없으면 현재 학년
        "error": error, "draft": draft, "draft_grade": draft_grade or roadmap.parse_grade(open_) or plan.grade,
        "recs": logic.recommend(db, user, limit=3),  # 로드맵과 이어지는 실제 공고 (가짜 공고를 만들지 않음)
    }, status_code=status)


def back_to(grade: int, item: "roadmap.Item | None" = None) -> RedirectResponse:
    """바꾼 뒤 로드맵으로 돌아가되, 그 항목의 학년 구역을 열어 둔 채 방금 누른 줄 위치로.
    (현재 학년이 아닌 구역에서 눌러도 구역이 닫히지 않게 open을 붙임. 303: 새로고침해도 같은 요청이 또 가지 않게)"""
    return RedirectResponse(f"/roadmap?open={grade}" + (f"#{item.anchor}" if item else f"#grade-{grade}"), status_code=303)


@app.get("/roadmap", response_class=HTMLResponse)
def roadmap_page(request: Request, open: str = "", db: Session = Depends(get_db), user: User = Depends(require_user)):
    return render_roadmap(request, db, user, open_=open)


@app.post("/roadmap/toggle")
def roadmap_toggle(key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        item = roadmap.toggle(db, user, key)
    except roadmap.NotFound:
        raise HTTPException(404, "없는 항목입니다")  # 원본 목록에 없거나 남의 항목
    return back_to(item.grade, item)


@app.post("/roadmap/hide")
def roadmap_hide(key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        item = roadmap.set_hidden(db, user, key, True)
    except roadmap.NotFound:
        raise HTTPException(404, "없는 항목입니다")
    return back_to(item.grade)


@app.post("/roadmap/restore")
def roadmap_restore(key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        item = roadmap.set_hidden(db, user, key, False)
    except roadmap.NotFound:
        raise HTTPException(404, "없는 항목입니다")
    return back_to(item.grade, item)


@app.post("/roadmap/custom", response_class=HTMLResponse)
def roadmap_add(request: Request, text: str = Form(""), grade: str = Form(""), db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    text = text.strip()
    g = roadmap.parse_grade(grade)
    problem = roadmap.custom_error(db, user, text, g)
    if problem:  # 다시 그릴 때 고른 학년 구역을 열고, 입력한 글과 학년을 그대로 남김
        return render_roadmap(request, db, user, open_=str(g or ""), error=problem, draft=text[:roadmap.TEXT_MAX],
                              draft_grade=g, status=400)
    return back_to(g, roadmap.add_custom(db, user, text, g))


@app.post("/roadmap/custom/delete")
def roadmap_delete(key: str = Form(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        grade = roadmap.delete_custom(db, user, key)
    except roadmap.NotFound:
        raise HTTPException(404, "없는 항목입니다")
    return back_to(grade)


# ---------- 로드맵 결과: 1~4학년 정리 + 고른 진로 방향의 학년별 가이드 ----------
def render_result(request: Request, db: Session, user: User, error: str = "", status: int = 200):
    r = roadmap_result.result_for(db, user)
    return templates.TemplateResponse(request, "roadmap_result.html", {
        "user": user, "r": r, "error": error, "paths_all": roadmap_data.PATHS, "side": "result",
        "recruit_link": lambda p: "/recruit?" + urlencode(p["link"]),  # 관련 공고 보기: 기존 인턴·채용 검색 재사용
    }, status_code=status)


@app.get("/roadmap/result", response_class=HTMLResponse)
def roadmap_result_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return render_result(request, db, user)


@app.post("/roadmap/paths", response_class=HTMLResponse)
async def roadmap_paths(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    keys = [str(k) for k in (await request.form()).getlist("path")]  # 체크박스는 여러 값이 같은 이름으로 옴
    problem = roadmap_result.path_error(keys)
    if problem:
        return render_result(request, db, user, error=problem, status=400)  # 실패하면 저장된 선택은 그대로
    roadmap_result.save_paths(db, user, keys)
    return RedirectResponse("/roadmap/result#paths", status_code=303)


def one_selected(values: list[str]) -> str:
    """카테고리 바(폰) 하위 줄에 표시할 선택: 하나만 골랐을 때만 그 이름, 여러 개면 아무것도 표시 안 함"""
    return values[0] if len(values) == 1 else ("*" if values else "")


def list_view(request: Request, template: str, path: str, items: list, current: dict, *, sort: str, page: str,
              extra: dict, saved: set[int]) -> HTMLResponse:
    """목록 화면 3개가 같이 쓰는 마무리: 정렬 → 20개씩 자르기 → 링크·숨은 칸 만들기 → 그리기"""
    pg = listing.paginate(listing.sort_items(items, sort), listing.parse_page(page))
    link = make_link(path, {**current, "sort": sort})
    filter_keys = ("category", "sector", "period", "region", "mine", "show_closed")
    return templates.TemplateResponse(request, template, {
        **extra, "pg": pg, "saved": saved, "link": link, "sort": sort, "sorts": listing.SORTS, "periods": listing.PERIODS,
        "action": path, "f": current, "regions": logic.REGIONS,
        "active_filters": sum(1 for k in filter_keys if current.get(k)),
        "search_hidden": listing.hidden_fields({**current, "sort": sort}, drop=("q",)),
        "filter_hidden": listing.hidden_fields({k: current.get(k) for k in ("scope", "q")} | {"sort": sort}),
        "reset_href": make_link(path, {"scope": current.get("scope", "")})(),
    })


@app.get("/opportunities", response_class=HTMLResponse)
def opportunity_list(request: Request, scope: str = "", category: list[str] = Query([]), q: str = "", period: str = "",
                     region: list[str] = Query([]), sort: str = "", page: str = "1", show_closed: bool = False,
                     db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    """대외활동(scope=외부)·교내 프로그램(scope=교내)·전체 목록. 분류는 여러 개 고를 수 있음(?category=a&category=b)"""
    category, region = listing.clean(category), listing.clean(region)
    period, sort = listing.norm_period(period), listing.norm_sort(sort)
    query = select(Opportunity)
    if scope:
        query = query.where(Opportunity.scope == scope)
    if category:
        query = query.where(Opportunity.category.in_(category))
    if not show_closed:
        query = query.where(logic.open_clause(date.today()))
    items = listing.narrow(list(db.scalars(query).all()), q=q, period=period, regions=region)
    current = {"scope": scope, "q": q, "category": category, "period": period, "region": region,
               "show_closed": "true" if show_closed else ""}
    # 분류 선택지는 DB에 실제로 있는 이름만 (교내·대외활동 각각, 전체면 모두)
    cat_query = select(Opportunity.category).distinct()
    cat_names = sorted(set(db.scalars(cat_query.where(Opportunity.scope == scope) if scope else cat_query)) - {""})
    link = make_link("/opportunities", current)
    catbar = build_catbar(scope or "all", show_closed, cat_names if scope else [], one_selected(category),
                          lambda v: link(category=v))
    title = {"교내": "교내 프로그램", "외부": "대외활동"}.get(scope, "전체 활동")
    return list_view(request, "opportunities.html", "/opportunities", items, current, sort=sort, page=page, extra={
        "user": user, "scope": scope, "title": title, "catbar": catbar, "cat_names": cat_names, "unit": "개",
    }, saved=bookmarks.saved_ids(db, user))


@app.get("/recruit", response_class=HTMLResponse)
def recruit(request: Request, q: str = "", kind: str = "", sector: list[str] = Query([]), region: list[str] = Query([]),
            category: list[str] = Query([]), period: str = "", sort: str = "", page: str = "1", mine: bool = False,
            show_closed: bool = False, db: Session = Depends(get_db), user: User | None = Depends(current_user)):
    """인턴·채용 칸: 취업·현장실습 공고를 분야·지역·분류·기간으로 걸러 보기"""
    sector, region, category = listing.clean(sector), listing.clean(region), listing.clean(category)
    period, sort = listing.norm_period(period), listing.norm_sort(sort)
    today = date.today()
    every = [o for o in db.scalars(select(Opportunity)).all() if logic.is_recruit(o)]
    cat_names = sorted({o.category for o in every} - {""})
    items = every if show_closed else [o for o in every if logic.is_open(o, today)]
    if kind:  # 화면의 선택 칸은 없앴지만 예전 주소(?kind=...)가 깨지지 않게 남겨 둠
        items = [o for o in items if logic.recruit_kind(o) == kind]
    if sector:
        items = [o for o in items if logic.recruit_sector(o) in sector]
    if category:
        items = [o for o in items if o.category in category]
    if mine and user:
        my = logic.user_tag_ids(user)
        items = [o for o in items if any(t.id in my for t in o.tags)]
    items = listing.narrow(items, q=q, period=period, regions=region, today=today)
    my_tags = []
    if user:
        my_tags = list(dict.fromkeys([t.name for t in user.department.tags] + [t.name for t in user.tags]))[:3]
    current = {"q": q, "kind": kind, "sector": sector, "region": region, "category": category, "period": period,
               "mine": "true" if mine else "", "show_closed": "true" if show_closed else ""}
    link = make_link("/recruit", current)
    catbar = build_catbar("recruit", show_closed, logic.SECTORS, one_selected(sector), lambda v: link(sector=v))
    return list_view(request, "recruit.html", "/recruit", items, current, sort=sort, page=page, extra={
        "user": user, "title": "인턴·채용", "catbar": catbar, "cat_names": cat_names, "sectors": logic.SECTORS,
        "mine": mine, "my_tags": my_tags, "unit": "건",
        "sector_of": logic.recruit_sector, "region_of": logic.recruit_region, "kind_of": logic.recruit_kind,
    }, saved=bookmarks.saved_ids(db, user))


@app.get("/opportunities/{opp_id}", response_class=HTMLResponse)
def opportunity_detail(opp_id: int, request: Request, db: Session = Depends(get_db),
                       user: User | None = Depends(current_user)):
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(404, "없는 활동입니다")
    rec = logic.score_opportunity(user, opp) if user else None
    avg = round(sum(r.rating for r in opp.reviews) / len(opp.reviews), 1) if opp.reviews else None
    return templates.TemplateResponse(request, "opportunity.html", {"user": user, "o": opp, "rec": rec, "avg": avg,
                                                                    "saved": bookmarks.saved_ids(db, user)})


@app.post("/bookmarks/toggle")
def bookmark_toggle(opportunity_id: int = Form(...), next: str = Form(""), db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    """공고 저장/해제. 로그인 전이면 프로필 화면으로(401 처리), 없는 공고면 404. 돌아갈 주소는 사이트 안만 허용"""
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(404, "없는 활동입니다")
    bookmarks.toggle(db, user, opp)
    return RedirectResponse(bookmarks.safe_next(next), status_code=303)


@app.get("/saved", response_class=HTMLResponse)
def saved_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    items = bookmarks.saved_list(db, user)
    return templates.TemplateResponse(request, "saved.html", {"user": user, "items": items, "saved": {o.id for o in items}})


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
    """내 정보 삭제: 프로필·로그인 정보·후기·로드맵 기록·저장한 공고를 DB에서 지우고 쿠키도 지움"""
    if confirm != "yes":
        raise HTTPException(400, "삭제 확인란에 체크해 주세요")
    for r in db.scalars(select(Review).where(Review.user_id == user.id)).all():
        db.delete(r)
    for e in db.scalars(select(RoadmapEntry).where(RoadmapEntry.user_id == user.id)).all():
        db.delete(e)  # 로드맵 기록(체크·뺀 항목·직접 쓴 글)도 지움 (User 연결로도 지워지지만, 빠뜨리지 않게 직접 한 번 더)
    for b in db.scalars(select(Bookmark).where(Bookmark.user_id == user.id)).all():
        db.delete(b)  # 저장한 공고 기록도 지움
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
