"""路由共用的依賴：目前使用者、角色檢查、限流、來源 IP。"""
import math
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.rate_limiter import KeyedRateLimiter
from app.db import get_db
from app.errors import AppError, forbidden
from app.models import User
from app.services import auth as auth_service

# 告訴 FastAPI：access JWT 從 Authorization: Bearer 取得；沒帶會自動回 401
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return auth_service.get_user_from_access_token(db, token)


def require_it_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "it_admin":
        raise forbidden("需要 IT 管理員權限")
    return user


@lru_cache
def _ask_limiter() -> KeyedRateLimiter:
    per_min = get_settings().rate_limit_per_min
    return KeyedRateLimiter(capacity=per_min, refill_per_sec=per_min / 60)


def rate_limit_ask(user: User = Depends(get_current_user)) -> User:
    """提問會呼叫模型、成本高，每位使用者每分鐘最多 RATE_LIMIT_PER_MIN 次。"""
    allowed, wait = _ask_limiter().check(user.id)
    if not allowed:
        raise AppError(429, "rate_limited", "提問太頻繁，請稍後再試", {"Retry-After": str(math.ceil(wait))})
    return user


def client_ip(request: Request) -> str | None:
    """來源 IP。只有在設定信任反向代理時才採用 X-Real-IP，否則任何人都能偽造這個標頭。"""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        if forwarded.strip():
            return forwarded.strip()
    return request.client.host if request.client else None
