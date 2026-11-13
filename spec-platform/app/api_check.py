"""공공데이터포털 API 연결 시험용 스크립트.

인증키가 제대로 동작하는지, 응답이 어떤 모양인지 확인만 합니다. DB에는 아무것도 넣지 않습니다.

준비: spec-platform 폴더에 .env 파일을 만들고 아래 두 줄을 적습니다.
    DATA_GO_KR_KEY=마이페이지의_일반_인증키(Decoding)
    JOB_API_URL=API_상세페이지의_요청주소_그대로
실행: python -m app.api_check
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> dict[str, str]:
    """.env 파일을 읽어 {이름: 값}으로 돌려줌 (라이브러리 없이 직접 읽기)"""
    if not ENV_PATH.exists():
        raise SystemExit(f"[오류] .env 파일이 없습니다: {ENV_PATH}")
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            env[name.strip()] = value.strip().strip('"').strip("'")
    return env


def main():
    env = load_env()
    key, url = env.get("DATA_GO_KR_KEY", ""), env.get("JOB_API_URL", "")
    if not key or not url:
        raise SystemExit("[오류] .env에 DATA_GO_KR_KEY 와 JOB_API_URL 두 줄이 모두 있어야 합니다.")

    # 공공데이터포털 공통 요청변수. 이름이 다르면 API 상세페이지의 '요청변수' 표를 보고 고침.
    params = {"serviceKey": key, "pageNo": 1, "numOfRows": 3, "resultType": "json"}
    full_url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(full_url, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"[응답] HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[응답] HTTP {e.code} (오류)")
    except urllib.error.URLError as e:
        raise SystemExit(f"[오류] 서버에 연결하지 못했습니다: {e.reason}")

    # 인증키는 출력하지 않음. 응답 앞부분만 보여 줌.
    try:
        data = json.loads(body)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    except json.JSONDecodeError:
        print(body[:3000])  # XML이나 오류 메시지로 온 경우


if __name__ == "__main__":
    main()
