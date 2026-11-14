"""密碼雜湊、JWT、refresh token。

對應職缺：API 整合經驗（OAuth 2.0 身分驗證）
規格測試：tests/spec/test_security.py
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

# Argon2id：刻意「慢」且吃記憶體的雜湊，讓資料庫外洩後的暴力破解成本很高。參數用套件預設值。
_hasher = PasswordHasher()
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    """回傳 Argon2id 雜湊字串。字串內含隨機 salt 與參數，所以同一個密碼每次結果都不同。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """密碼正確回 True；錯誤或雜湊格式不對都回 False，不把例外丟給呼叫端。"""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """雜湊參數過時（例如套件升級提高強度）時回 True，登入成功後順便重算。"""
    return _hasher.check_needs_rehash(password_hash)


def burn_verify_time(password: str) -> None:
    """帳號不存在時也跑一次驗證，讓「帳號不存在」和「密碼錯誤」花的時間相同，避免被用回應時間猜出帳號。"""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("timing-equalizer")
    verify_password(password, _dummy_hash)


def create_access_token(user) -> str:
    """簽發 access JWT。

    payload 只放識別用的資料；權限判斷時仍以資料庫中的使用者為準，
    所以 IT 修改角色或停用帳號會立刻生效，不必等 JWT 到期。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),            # JWT 規範要求 sub 是字串
        "dept": user.dept_id,
        "role": user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_ttl_min),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_access_token(token: str) -> dict | None:
    """驗證並解開 JWT；過期、簽章錯誤、格式錯誤都回 None。

    algorithms 一定要指定：否則攻擊者可以把 header 改成 alg=none，送出沒有簽章的權杖。
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg],
                             options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == "access" else None


def hash_token(raw_token: str) -> str:
    """refresh token 的 SHA-256（64 個十六進位字元）。資料庫只存這個。

    密碼需要 Argon2，是因為人選的密碼可能很短、可以被猜；
    refresh token 是 32 位元組的隨機值，無法暴力猜測，快速的 SHA-256 就足夠。
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """產生 refresh token，回傳 (原文, 雜湊)。原文放進使用者的 cookie，雜湊存資料庫。"""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
