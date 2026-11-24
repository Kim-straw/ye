"""UI 개편: 시작(로딩) 화면·서비스 워커·앱 아이콘, 홈 화면"""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_splash_is_static_and_has_no_personal_data():
    c = TestClient(app)
    r = c.get("/static/splash.html")
    assert r.status_code == 200 and 'id="splash"' in r.text
    assert "스펙로드" in r.text and "비공식 학생 프로젝트" in r.text and "서버를 깨우는 중이에요" in r.text
    # 개인 정보·템플릿 문법이 없는 순수 정적 파일 (폰에 저장되는 파일이므로)
    assert "{{" not in r.text and "{%" not in r.text and "nickname" not in r.text
    # 다른 주소로 보내지 않음: 같은 주소 다시 불러오기만
    assert "location.reload()" in r.text
    assert not re.search(r"location\.(href|assign|replace)|window\.open|\?next=", r.text)
    assert "90000" in r.text and '"/healthz"' in r.text


def test_service_worker_splash_rules():
    sw = (STATIC / "sw.js").read_text()
    m = re.search(r'const CACHE = "specroad-v(\d+)"', sw)
    assert m and int(m.group(1)) >= 15
    assert '"/static/splash.html"' in sw.split("const SHELL")[1].split("];")[0]  # 미리 저장 목록에 있음
    assert "SPLASH_AFTER_MS = 1500" in sw
    assert 'if (req.method !== "GET") return;' in sw                              # POST(로그인·폼 제출)는 가로채지 않음
    assert 'req.mode === "navigate" && !path.startsWith("/api/")' in sw
    assert 'path.startsWith("/static/")' in sw and 'path === "/healthz"' in sw   # 정적 파일·서버 확인 요청에는 시작 화면 없음


def test_manifest_matches_splash_color():
    m = json.loads((STATIC / "manifest.webmanifest").read_text())
    splash = (STATIC / "splash.html").read_text()
    assert m["background_color"].lower() == "#862633" and "background: var(--brand)" in splash and "--brand: #862633" in splash
    purposes = {i.get("purpose", "any") for i in m["icons"]}
    assert "maskable" in purposes
    for i in m["icons"]:
        assert (STATIC / Path(i["src"]).name).exists(), i["src"]
    assert 'href="/static/icon-maskable-512.png"' in TestClient(app).get("/").text   # 아이폰 홈 화면 아이콘


def test_requirements_unchanged():
    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    assert "reportlab" not in req and "fpdf" not in req


# ---------- 홈 ----------
from datetime import date, timedelta  # noqa: E402

from app import seed  # noqa: E402
from app.db import Opportunity, SessionLocal  # noqa: E402
from tests.helpers import dept_id, tag_id  # noqa: E402


def add_opp(title, deadline_days=None, posted_days_ago=0, sample=False, scope="외부"):
    db = SessionLocal()
    o = Opportunity(scope=scope, category="공모전", title=title, host="시험주관", source="manual", url="https://example.org/" + title,
                    deadline=(date.today() + timedelta(days=deadline_days)) if deadline_days is not None else None,
                    posted_at=date.today() - timedelta(days=posted_days_ago), is_sample=sample)
    db.add(o); db.commit(); db.close()


def strip(html):
    m = re.search(r'<div class="hero-strip">(.*?)</div>\s*</section>', html, re.S)
    return re.findall(r'<span class="hero-title">([^<]+)</span>', m.group(1)) if m else None


def feed_titles(html):
    sec = html.split('id="feed"')[1]
    return re.findall(r'<h3 class="item-title">([^<]+)</h3>', sec)


def setup_function():
    seed.run()


def test_home_urgent_strip_real_open_nearest_five():
    for i, d in enumerate([9, 2, 0, 30, 5, 14, 1]):
        add_opp(f"마감{d}일", deadline_days=d)
    add_opp("마감지남", deadline_days=-1)
    add_opp("샘플글", deadline_days=1, sample=True)
    add_opp("마감없음", deadline_days=None)
    html = TestClient(app).get("/").text
    assert strip(html) == ["마감0일", "마감1일", "마감2일", "마감5일", "마감9일"]       # 가까운 순 5개, 지남·샘플·마감일 없음 제외
    assert "D-DAY" in html
    # '마감 임박' 탭은 위 영역에 나온 공고를 빼고 그다음
    assert feed_titles(TestClient(app).get("/?tab=urgent").text) == ["마감14일", "마감30일"]


def test_home_without_deadlines_hides_strip():
    add_opp("마감없는 글", deadline_days=None)
    html = TestClient(app).get("/").text
    assert strip(html) is None and 'class="hero-strip"' not in html
    assert "마감없는 글" in feed_titles(html)                                     # 새 공고 탭에는 보임


def test_home_tabs_and_intro_and_search():
    add_opp("새 글", deadline_days=None)
    anon = TestClient(app)
    page = anon.get("/").text
    assert 'class="home-intro"' in page and "1분 만에 시작하기" in page          # 소개 블록은 로그인 전만
    assert re.search(r'<form class="searchbar" method="get" action="/recruit"', page) and 'name="q"' in page
    assert 'href="/?tab=mine#feed"' not in page                                   # 내 분야 탭은 로그인해야
    assert re.search(r'href="/\?tab=new#feed" class="on"', anon.get("/?tab=hacker").text)   # 모르는 값 -> 새 공고
    assert re.search(r'href="/\?tab=new#feed" class="on"', anon.get("/?tab=mine").text)     # 로그인 전 mine -> 새 공고
    for href in ['/opportunities?scope=교내', '/opportunities?scope=외부', '/recruit', '/roadmap']:
        assert f'href="{href}"' in page
    db = SessionLocal()                                                           # 내 분야(반도체)와 맞는 열린 공고 하나
    from app.db import Tag
    db.add(Opportunity(scope="외부", category="공모전", title="반도체 공정 공모전", host="시험주관", source="manual",
                       url="https://example.org/semi", posted_at=date.today(), deadline=date.today() + timedelta(days=20),
                       tags=[db.query(Tag).filter_by(name="반도체").one()]))
    db.commit(); db.close()
    c = TestClient(app)
    r = c.post("/profile", data={"nickname": "홈", "department_id": dept_id("반도체물리학부"), "grade": 1,
                                 "admission_year": 2025, "tag_ids": [tag_id("반도체")]}, follow_redirects=False)
    c.cookies.set("user_id", r.cookies["user_id"])
    page = c.get("/").text
    assert 'class="home-intro"' not in page                                       # 로그인 후에는 소개 블록 없음
    mine = c.get("/?tab=mine").text
    assert re.search(r'href="/\?tab=mine#feed" class="on"', mine) and 'href="/me"' in mine   # 추천이 있으면 내 분야 탭
    assert feed_titles(mine) == ["반도체 공정 공모전"]
