"""쿠키 위조 방지: 사용자 번호에 '서명'을 붙여 저장합니다.

비유: 번호표에 도장을 찍어 두는 것. 도장(서명)은 서버만 찍을 수 있어서,
쿠키의 번호를 1에서 2로 바꿔 남의 프로필로 들어가려 해도 도장이 안 맞아 거절됩니다.
비밀키는 환경변수 SPEC_SECRET 또는 spec-platform/.secret 파일(처음 실행 때 자동 생성, 깃허브에 올라가지 않음)에서 읽습니다.
"""
import hashlib
import hmac
import os
import secrets
from pathlib import Path

SECRET_FILE = Path(__file__).resolve().parent.parent / ".secret"


def _secret() -> bytes:
    env = os.environ.get("SPEC_SECRET")
    if env:
        return env.encode()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
    return SECRET_FILE.read_text().strip().encode()


def _mac(user_id: int) -> str:
    return hmac.new(_secret(), str(user_id).encode(), hashlib.sha256).hexdigest()[:32]


def sign(user_id: int) -> str:
    """사용자 번호 -> '번호.서명' 글자"""
    return f"{user_id}.{_mac(user_id)}"


def verify(value: str | None) -> int | None:
    """쿠키 글자가 진짜면 사용자 번호, 위조·형식 오류면 None"""
    if not value or "." not in value:
        return None
    raw, _, sig = value.partition(".")
    if not raw.isdigit():
        return None
    return int(raw) if hmac.compare_digest(sig, _mac(int(raw))) else None
