# 스펙로드 (MVP)

고려대학교 세종캠퍼스 학생을 위한 스펙·대외활동 통합 플랫폼입니다.
프로필 입력 → 교내 프로그램·대외활동 추천 → 직무별 스펙 갭 분석까지 이어집니다.
폰에 앱처럼 설치할 수 있는 웹앱(PWA)입니다.

> 활동은 학교 게시판 RSS의 **실제 공지만** 넣습니다(가상 활동 없음). 직무 요건은 아직 샘플이고, 학과명은 확인되지 않았습니다.

## 실행 방법 (Windows, VS Code 터미널 기준)

```bash
cd spec-platform
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed              # 기본값 + 확인된 실제 학교 공지 (가상 활동 없음)
python -m app.rss_import        # 학교 게시판 RSS에서 실제 공지 가져오기 (인터넷 필요)
python -m app.job_import --dump # (.env 필요) 채용공고 API 응답 항목 이름만 확인, DB 변경 없음
python -m app.job_import        # 진행 중인 공공기관 채용공고를 받아 직무·자격요건으로 저장
uvicorn app.main:app --reload   # 서버 켜기
```

- `seed`는 DB를 통째로 다시 만듭니다. 그래서 순서는 항상 **seed → rss_import → job_import** 입니다.
- `job_import`에는 `.env`가 필요합니다 (`.env`는 깃허브에 올라가지 않습니다).
  ```
  DATA_GO_KR_KEY=Decoding_인증키
  JOB_API_URL=https://apis.data.go.kr/1051000/recruitment/list
  ```
- 실제 채용공고가 DB에 하나라도 있으면 직무 화면에는 그것만 보이고, 없을 때만 샘플 직무가 보입니다.
- 공고 글에서 스펙 단어를 찾아 요건으로 만드는 방식(`SPEC_PATTERNS`)이라 빠지거나 틀릴 수 있습니다. 화면에 원문 링크를 함께 보여 줍니다.
- 수집할 게시판은 `app/rss_import.py`의 `FEEDS` 목록에서 관리합니다. **로그인 없이 열리는 것을 확인한 RSS 주소만** 넣습니다.
- RSS에는 마감일이 없어서, 마감일 없는 학교 공지는 **게시 후 60일까지만** 목록과 추천에 나옵니다 (`logic.py`의 `FRESH_DAYS`).

- 화면: http://localhost:8000
- API 문서(직접 눌러 보기): http://localhost:8000/docs
- 자동 점검: `python -m pytest -q`

### 폰에서 열어 보기 (같은 와이파이)
```bash
uvicorn app.main:app --reload --host 0.0.0.0
```
PC의 IP 주소(`ipconfig`로 확인)로 `http://192.168.x.x:8000` 접속.
단, "홈 화면에 추가"로 앱처럼 설치하는 기능은 보안상 **https 주소**나 localhost에서만 완전히 동작합니다. 배포 단계에서 해결합니다.

## 폴더 구조

```
spec-platform/
├── app/
│   ├── main.py      홀: 주소별 처리 (화면 + /api JSON)
│   ├── db.py        창고: DB 연결 + 테이블 14개 정의
│   ├── logic.py     레시피: 추천 점수, 갭 분석 (규칙 기반)
│   ├── seed.py      샘플 데이터
│   ├── templates/   화면 양식 (Jinja2)
│   └── static/      CSS, 아이콘, PWA 파일(manifest, sw.js)
├── tests/           자동 점검
└── docs/DESIGN.md   설계 문서 (ERD, 규칙, 마일리지 설계안)
```

## 자주 나는 에러

| 증상 | 원인 | 해결 |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` | `spec-platform` 폴더 밖에서 실행 | `cd spec-platform` 후 다시 실행 |
| `no such table` | 샘플 데이터를 안 넣음 | `python -m app.seed` |
| 화면이 옛날 디자인 그대로 | 서비스 워커가 CSS를 저장해 둠 | 브라우저 강력 새로고침(Ctrl+Shift+R) 또는 `sw.js`의 `CACHE` 버전 숫자 올리기 |
| `Address already in use` | 서버가 이미 켜져 있음 | 기존 터미널에서 Ctrl+C 또는 `--port 8001` |

## 폰에서 열기

- **같은 와이파이**: `uvicorn app.main:app --host 0.0.0.0 --port 8000` 으로 켜고, 폰에서 `http://(PC의 IPv4 주소):8000` 접속. 방화벽에서 "개인 네트워크" 허용 필요.
- **와이파이와 상관없이(터널)**: 서버를 켠 채로 다른 PowerShell에서 `cloudflared tunnel --url http://localhost:8000` 을 실행하면 `https://....trycloudflare.com` 주소가 나옵니다.
  - 이 주소는 실행할 때마다 바뀌고, **주소를 아는 사람은 누구나** 접속할 수 있습니다. 믿는 사람에게만 알려 주세요.
  - 쿠키에 서명을 붙여 남의 프로필로 들어가는 위조는 막았지만, 로그인(본인 확인)은 아직 없습니다.
  - 서명 비밀키는 `.secret` 파일(처음 실행 때 자동 생성)에 있습니다. 이 파일은 깃허브에 올리지 마세요(.gitignore에 들어 있음).
