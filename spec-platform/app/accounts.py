"""로그인: 아이디·비밀번호 확인과 무차별 대입(비밀번호 계속 찍어 보기) 막기.

비밀번호는 원문을 저장하지 않고 '해시'만 저장합니다.
비유: 비밀번호를 믹서기에 갈아서(해시) 그 가루만 보관. 가루로는 원래 비밀번호를 되돌릴 수 없지만,
로그인할 때 입력한 비밀번호를 같은 방식으로 갈아 보면 같은 가루가 나오는지로 맞는지 알 수 있습니다.
- salt: 사람마다 다른 소금을 넣고 갈아서, 같은 비밀번호라도 가루가 다르게 나옴(미리 계산한 표로 맞추기 방지)
- 600,000번 반복: 한 번 확인에 일부러 시간이 걸리게 해서, 훔친 가루로 비밀번호를 하나하나 맞춰 보기 어렵게 함
새 라이브러리 없이 파이썬 기본 기능(hashlib)만 씁니다.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time

ITERATIONS = 600_000
LOGIN_ID_RE = re.compile(r"^[a-z0-9_]{4,20}$")
PW_MIN, PW_MAX = 8, 72


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)  # 걸리는 시간으로 정답을 짐작하지 못하게 하는 비교


# 없는 아이디로 로그인할 때도 같은 시간이 걸리게 하려고 쓰는 가짜 해시 (어떤 아이디가 있는지 시간으로 알아내지 못하게)
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_login(password: str, stored: str | None) -> bool:
    if stored is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


def normalize_login_id(raw: str) -> str:
    return (raw or "").strip().lower()


def account_error(login_id: str, password: str, password2: str | None = None) -> str | None:
    """형식이 틀리면 한 줄 오류 문구, 맞으면 None"""
    if not LOGIN_ID_RE.match(login_id):
        return "아이디는 영문 소문자·숫자·밑줄(_)로 4~20자예요"
    if not (PW_MIN <= len(password) <= PW_MAX):
        return f"비밀번호는 {PW_MIN}~{PW_MAX}자로 정해 주세요"
    if password2 is not None and password != password2:
        return "비밀번호 확인이 맞지 않아요"
    return None


class LoginLimiter:
    """비밀번호를 계속 찍어 보는 시도를 막음. 두 겹으로 막음:
    1) 같은 (IP, 아이디)로 WINDOW초 안에 LIMIT번 틀리면 막음
    2) IP와 상관없이 같은 아이디로 WINDOW초 안에 ID_LIMIT번 틀리면 막음
       - 서버 설정(--forwarded-allow-ips='*') 때문에 접속자가 X-Forwarded-For 값을 바꿔서 IP를 속일 수 있어서, IP만 보는 1)은 우회될 수 있음
       - 대가: 남이 내 아이디로 일부러 틀려서 WINDOW초(10분) 동안 나를 잠시 못 들어오게 할 수 있음 (비밀번호가 뚫리는 것보다 낫다고 판단)
    한계: 서버 메모리에만 기억하므로 서버가 다시 켜지면(무료 Render는 자주 잠듦) 기록이 지워짐."""
    LIMIT, ID_LIMIT, WINDOW = 5, 20, 600
    MAX_KEYS = 10_000  # 아무 아이디로 계속 시도해 메모리를 채우는 것을 막는 상한

    def __init__(self):
        self._fails: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key, now):
        items = [t for t in self._fails.get(key, []) if now - t < self.WINDOW]
        if items:
            self._fails[key] = items
        else:
            self._fails.pop(key, None)  # 오래된 기록은 지움
        return items

    def _prune(self, now):
        if len(self._fails) > self.MAX_KEYS:
            for key in list(self._fails):
                self._recent(key, now)
            if len(self._fails) > self.MAX_KEYS:  # 그래도 많으면 가장 오래된 절반을 버림
                for key in sorted(self._fails, key=lambda k: self._fails[k][-1])[: len(self._fails) // 2]:
                    del self._fails[key]

    def blocked(self, ip: str, login_id: str) -> bool:
        with self._lock:
            now = time.monotonic()
            return (len(self._recent((ip, login_id), now)) >= self.LIMIT
                    or len(self._recent(("*", login_id), now)) >= self.ID_LIMIT)

    def fail(self, ip: str, login_id: str):
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            for key in ((ip, login_id), ("*", login_id)):
                self._fails.setdefault(key, []).append(now)

    def reset(self, ip: str, login_id: str):
        """로그인에 성공하면 이 IP의 실패 기록만 지움 (아이디 전체 기록은 남겨서, 남의 IP에서 맞춰 본 시도가 지워지지 않게)"""
        with self._lock:
            self._fails.pop((ip, login_id), None)


limiter = LoginLimiter()
