"""密碼雜湊、JWT、refresh token。

對應職缺：API 整合經驗（OAuth 2.0 身分驗證）
規格測試：tests/spec/test_security.py
套件：argon2-cffi（argon2.PasswordHasher）、PyJWT（import jwt）、標準庫 secrets、hashlib
"""
from app.models import User


def hash_password(password: str) -> str:
    """TODO：回傳 Argon2id 雜湊字串（每次結果不同，內含隨機 salt）。"""
    raise NotImplementedError("core.security.hash_password 尚未實作")


def verify_password(password: str, password_hash: str) -> bool:
    """TODO：密碼正確回 True，錯誤回 False（不要丟例外）。"""
    raise NotImplementedError("core.security.verify_password 尚未實作")


def create_access_token(user: User) -> str:
    """TODO：簽發 access JWT。

    payload：sub=str(user.id)、dept=user.dept_id、role=user.role、iat、exp（現在 + access_ttl_min）
    """
    raise NotImplementedError("core.security.create_access_token 尚未實作")


def decode_access_token(token: str) -> dict | None:
    """TODO：驗證並解開 JWT；過期、簽章錯誤、格式錯誤都回 None。

    思考：decode 時為什麼一定要指定 algorithms？
    """
    raise NotImplementedError("core.security.decode_access_token 尚未實作")


def hash_token(raw_token: str) -> str:
    """TODO：refresh token 的 SHA-256 十六進位字串（64 字元）。資料庫只存這個。

    思考：密碼用 Argon2，為什麼 refresh token 用 SHA-256 就夠？
    """
    raise NotImplementedError("core.security.hash_token 尚未實作")


def new_refresh_token() -> tuple[str, str]:
    """TODO：產生 refresh token，回傳 (原文, 雜湊)。原文給使用者，雜湊存資料庫。"""
    raise NotImplementedError("core.security.new_refresh_token 尚未實作")
