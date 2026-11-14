"""規格：app/core/security.py"""
from types import SimpleNamespace

from app.core import security

USER = SimpleNamespace(id=7, dept_id=3, role="manager")


def test_hash_is_not_plaintext_and_differs_each_time():
    h1, h2 = security.hash_password("correct horse"), security.hash_password("correct horse")
    assert "correct horse" not in h1
    assert h1 != h2                      # 隨機 salt


def test_verify_password():
    h = security.hash_password("correct horse")
    assert security.verify_password("correct horse", h) is True
    assert security.verify_password("wrong", h) is False


def test_access_token_roundtrip():
    payload = security.decode_access_token(security.create_access_token(USER))
    assert payload["sub"] == "7"
    assert payload["dept"] == 3
    assert payload["role"] == "manager"
    assert payload["exp"] > payload["iat"]


def test_tampered_or_garbage_token_returns_none():
    token = security.create_access_token(USER)
    assert security.decode_access_token(token[:-2] + "xx") is None
    assert security.decode_access_token("not-a-jwt") is None


def test_expired_token_returns_none(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "access_ttl_min", -1)   # 簽發當下就已過期
    assert security.decode_access_token(security.create_access_token(USER)) is None


def test_refresh_token_is_random_and_only_hash_is_stored():
    raw1, hash1 = security.new_refresh_token()
    raw2, _ = security.new_refresh_token()
    assert raw1 != raw2
    assert len(raw1) >= 32
    assert hash1 == security.hash_token(raw1)
    assert len(hash1) == 64 and raw1 not in hash1
