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
