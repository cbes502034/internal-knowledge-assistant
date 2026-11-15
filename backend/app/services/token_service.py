"""
【檔案用途】refresh token 的簽發、輪替與撤銷。
對應職缺：OAuth 2.0（refresh_token grant）、資訊安全。

為什麼要 refresh token？access token 只有 15 分鐘，短效是為了「被偷了也很快失效」；
但每 15 分鐘就要重新輸入密碼太痛苦，所以另外發一張存在 HttpOnly cookie 的 refresh token，
JavaScript 讀不到它（防 XSS 偷取），過期前用它換新的 access token。

三個安全設計：
  1. 只存雜湊：資料庫外洩，攻擊者也拿不到可用的 token。
  2. 輪替（rotation）：每用一次就作廢、換一張新的。
  3. 重複使用偵測：已作廢的 token 又被拿來用，代表很可能被偷了 → 把這個人所有 token 全部作廢。

被誰呼叫：routers/auth.py（登入、續期、登出）、routers/users.py（停用帳號時全部作廢）。
"""

import hashlib  # SHA-256 雜湊
import secrets  # 密碼學等級的亂數（不能用 random：random 可被預測，不適合產生憑證）
from datetime import datetime, timedelta, timezone  # 計算到期時間、比較時間差；timezone.utc 確保用 UTC

from sqlalchemy import select, update  # 組 SELECT 與 UPDATE 查詢
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.config import settings  # 讀 refresh_token_hours、idle_timeout_minutes
from app.models.audit import RefreshToken  # refresh_tokens 資料表
from app.models.user import User  # 查 token 的擁有者

# 同一個瀏覽器開兩個分頁、同時換 token 時，慢的那個會拿到剛被作廢的舊 token。
# 作廢後幾秒內的重複使用視為這種競態，只拒絕、不觸發「全部作廢」，避免把正常使用者踢出去
REUSE_GRACE_SECONDS = 10


class RefreshTokenError(Exception):
    """refresh token 無效、過期、已撤銷或閒置太久；呼叫端應回 401 並清掉 cookie。"""


def _hash(raw: str) -> str:
    """把原始 token 字串轉成 SHA-256 十六進位字串（資料庫只存這個）。"""
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    """目前時間（UTC、帶時區）；集中成一個函式，所有比較都用同一種時間格式。"""
    return datetime.now(timezone.utc)


def issue_refresh_token(db: Session, user: User) -> str:
    """簽發新 token：產生亂數、存雜湊，回傳原始字串（只有這一次拿得到，之後資料庫裡只剩雜湊）。不 commit。"""
    raw = secrets.token_urlsafe(32)  # 32 bytes 亂數，暴力猜不到；urlsafe 代表可以安全放進 cookie
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash(raw),
            expires_at=_now() + timedelta(hours=settings.refresh_token_hours),
        )
    )
    # 不在這裡 commit：讓呼叫端把「簽發新 token」和其他變更（例如作廢舊 token）放在同一個交易
    return raw


def revoke_all(db: Session, user_id: int) -> None:
    """作廢某人所有還有效的 token（停用帳號、偵測到 token 被偷時用）。不 commit。"""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))  # 只改還沒作廢的
        .values(revoked_at=_now())
    )


def rotate_refresh_token(db: Session, raw: str) -> tuple[User, str]:
    """用舊 token 換新 token；任何一關不過就拋 RefreshTokenError。成功時已 commit。"""
    # ── 第 1 關：token 存在嗎 ──
    # with_for_update：鎖住這一列，兩個請求同時拿同一張 token 來換時，只有一個能成功
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)).with_for_update())
    if token is None:
        raise RefreshTokenError("無效的 refresh token")

    # ── 第 2 關：是否已作廢（含重複使用偵測）──
    now = _now()
    if token.revoked_at is not None:
        if now - token.revoked_at > timedelta(seconds=REUSE_GRACE_SECONDS):
            # 已經作廢很久的 token 又出現 → 很可能是被偷了，正主與小偷手上的全部作廢
            revoke_all(db, token.user_id)
            db.commit()
        raise RefreshTokenError("refresh token 已失效")

    # ── 第 3 關：是否過期 ──
    if token.expires_at <= now:
        raise RefreshTokenError("登入已過期，請重新登入")

    # ── 第 4 關：帳號還在、還啟用嗎 ──
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenError("帳號不存在或已停用")

    # ── 第 5 關：伺服器端的閒置登出 ──
    # 前端的 15 分鐘計時可以被關掉或繞過，伺服器要自己再擋一次
    idle_limit = timedelta(minutes=settings.idle_timeout_minutes)
    if user.last_active_at is not None and now - user.last_active_at > idle_limit:
        token.revoked_at = now
        db.commit()
        raise RefreshTokenError("閒置過久，請重新登入")

    # ── 全部通過：輪替（舊的作廢、發新的），一次 commit ──
    token.revoked_at = now  # 輪替：舊的作廢
    new_raw = issue_refresh_token(db, user)
    user.last_active_at = now
    db.commit()
    return user, new_raw


def revoke_refresh_token(db: Session, raw: str) -> int | None:
    """登出：作廢這一張 token，回傳擁有者的 user_id（寫稽核用）；token 不存在回傳 None。"""
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    if token is None:
        return None
    # 已經作廢的就不重複寫，保留第一次作廢的時間
    if token.revoked_at is None:
        token.revoked_at = _now()
        db.commit()
    return token.user_id
