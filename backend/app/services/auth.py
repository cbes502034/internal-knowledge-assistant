"""註冊、登入、權杖更新、撤銷、由 JWT 取得使用者。（對應企劃書 圖 6 循序圖）"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import security
from app.errors import AppError, conflict, unauthorized
from app.models import RefreshToken, User
from app.services import audit
from app.services import user as user_service

# 每個請求都更新「最後活動時間」會變成每個請求都寫一次資料庫；超過這個間隔才寫，
# 閒置判斷的誤差最多就是這麼久，換來大幅減少寫入。
ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)

# 同一個瀏覽器開兩個分頁時，兩邊可能幾乎同時拿同一個 refresh token 來換。
# 剛被輪替（這段時間內）的舊 token 再出現，視為併發而不是外洩：只回 401，前端稍等再用新 cookie 重試。
REUSE_GRACE = timedelta(seconds=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _idle_timeout() -> AppError:
    return AppError(401, "idle_timeout", "閒置過久，請重新登入", {"WWW-Authenticate": "Bearer"})


def _is_idle(user: User, now: datetime) -> bool:
    limit = timedelta(minutes=get_settings().idle_timeout_min)
    return user.last_active_at is not None and now - user.last_active_at > limit


def _issue_tokens(db: Session, user: User) -> tuple[str, str]:
    """簽發 access JWT 與新的 refresh token（資料庫只存雜湊）。"""
    raw, token_hash = security.new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash,
                        expires_at=_now() + timedelta(hours=get_settings().refresh_ttl_hours)))
    return security.create_access_token(user), raw


def register_user(db: Session, *, email: str, password: str, dept_code: str) -> User:
    """註冊一般員工。角色一律是 employee，主管與 IT 由 IT 管理員調整。"""
    if not get_settings().allow_registration:
        raise AppError(403, "registration_disabled", "目前不開放自行註冊，請聯絡資訊單位")
    department = user_service.require_department(db, dept_code)
    email = _normalize_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise conflict("email_taken", "此 email 已註冊")
    user = User(email=email, password_hash=security.hash_password(password), dept_id=department.id, role="employee")
    db.add(user)
    try:
        # 先查再寫在「同時註冊」時仍可能撞在一起；交給資料庫的唯一約束做最後把關
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("email_taken", "此 email 已註冊") from None
    audit.record(db, user=user, action="user.register", target=f"user:{user.id}")
    db.commit()
    return user


def login(db: Session, *, email: str, password: str, ip: str | None) -> tuple[str, str]:
    """帳密登入，回傳 (access JWT, refresh token 原文)。

    帳號不存在、密碼錯誤、帳號停用一律回同一個訊息：不讓人從錯誤訊息猜出哪些帳號存在。
    連續失敗達上限就鎖定一段時間，擋下暴力猜密碼。
    """
    settings = get_settings()
    now = _now()
    user = db.scalar(select(User).where(User.email == _normalize_email(email)))
    if user is None:
        security.burn_verify_time(password)
        raise unauthorized("帳號或密碼錯誤")

    if user.locked_until is not None and user.locked_until > now:
        wait = int((user.locked_until - now).total_seconds()) + 1
        raise AppError(429, "too_many_attempts", "登入失敗次數過多，請稍後再試", {"Retry-After": str(wait)})

    if not security.verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lock_min)
            user.failed_logins = 0
            audit.record(db, user=user, action="login.locked", ip=ip)
        else:
            audit.record(db, user=user, action="login.failed", ip=ip)
        db.commit()
        raise unauthorized("帳號或密碼錯誤")

    if not user.is_active:
        raise unauthorized("帳號或密碼錯誤")

    user.failed_logins = 0
    user.locked_until = None
    user.last_active_at = now
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    access, raw_refresh = _issue_tokens(db, user)
    audit.record(db, user=user, action="login", ip=ip)
    db.commit()
    return access, raw_refresh


def refresh(db: Session, *, raw_refresh_token: str) -> tuple[str, str]:
    """用 refresh token 換新的 access JWT，並「輪替」refresh token（舊的作廢、發新的）。

    輪替的好處：每個 refresh token 只能用一次。若已作廢的 token 又被拿來用，
    代表有人複製了它（使用者或攻擊者其中一方拿的是舊的），這時撤銷此人全部權杖、要求重新登入。
    """
    now = _now()
    # FOR UPDATE：兩個請求同時帶同一個 token 時，第二個要等第一個輪替完才讀得到，不會各自換出一個新 token
    token = db.scalar(select(RefreshToken)
                      .where(RefreshToken.token_hash == security.hash_token(raw_refresh_token))
                      .with_for_update())
    if token is None:
        raise unauthorized()
    user = db.get(User, token.user_id)

    if token.revoked_at is not None:
        if now - token.revoked_at <= REUSE_GRACE:
            db.rollback()
            raise AppError(401, "refresh_superseded", "請重試", {"WWW-Authenticate": "Bearer"})
        user_service.revoke_all_tokens(db, token.user_id)
        audit.record(db, user=user, action="token.reuse_detected")
        db.commit()
        raise unauthorized()
    if token.expires_at <= now or user is None or not user.is_active:
        raise unauthorized()
    if _is_idle(user, now):
        token.revoked_at = now
        audit.record(db, user=user, action="logout.idle")
        db.commit()
        raise _idle_timeout()

    token.revoked_at = now
    user.last_active_at = now
    access, raw_new = _issue_tokens(db, user)
    db.commit()
    return access, raw_new


def revoke(db: Session, *, user: User, raw_refresh_token: str, ip: str | None = None) -> None:
    """登出：把這個 refresh token 標記為已撤銷。找不到或已撤銷就當作完成（冪等）。"""
    token = db.scalar(select(RefreshToken).where(
        RefreshToken.token_hash == security.hash_token(raw_refresh_token),
        RefreshToken.user_id == user.id))
    if token is not None and token.revoked_at is None:
        token.revoked_at = _now()
    audit.record(db, user=user, action="logout", ip=ip)
    db.commit()


def get_user_from_access_token(db: Session, token: str) -> User:
    """每個受保護的請求都會經過這裡。

    權限以資料庫為準（JWT 只用來識別是誰），所以停用帳號、修改角色會立刻生效。
    """
    payload = security.decode_access_token(token)
    if payload is None:
        raise unauthorized()
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()

    now = _now()
    if _is_idle(user, now):
        raise _idle_timeout()
    if user.last_active_at is None or now - user.last_active_at > ACTIVITY_WRITE_INTERVAL:
        user.last_active_at = now
        db.commit()
    return user
