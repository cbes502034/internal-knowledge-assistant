"""驗證端點：依 OAuth 2.0 規範命名（/auth/token、/auth/revoke）。"""
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import client_ip, get_current_user
from app.errors import AppError
from app.models import User
from app.schemas import TokenOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"          # cookie 只會送到 /auth 底下的端點，其他 API 不會帶著它


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, raw_token,
        max_age=settings.refresh_ttl_hours * 3600,
        httponly=True,                # JavaScript 讀不到，XSS 偷不走
        samesite="strict",            # 其他網站發出的請求不會帶這個 cookie（防 CSRF）
        secure=settings.cookie_secure,
        path=COOKIE_PATH,
    )


@router.post("/token", response_model=TokenOut)
def issue_token(
    request: Request,
    response: Response,
    grant_type: Literal["password", "refresh_token"] = Form(...),
    username: str | None = Form(default=None),       # OAuth2 規範的欄位名稱；這裡填 email
    password: str | None = Form(default=None),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
):
    """登入（grant_type=password）或更新權杖（grant_type=refresh_token）。"""
    if grant_type == "password":
        if not username or not password:
            raise AppError(400, "bad_request", "缺少帳號或密碼")
        access, raw_refresh = auth_service.login(db, email=username, password=password, ip=client_ip(request))
    else:
        if not refresh_token:
            raise AppError(401, "unauthorized", "請重新登入", {"WWW-Authenticate": "Bearer"})
        access, raw_refresh = auth_service.refresh(db, raw_refresh_token=refresh_token)

    _set_refresh_cookie(response, raw_refresh)
    return TokenOut(access_token=access, expires_in=get_settings().access_ttl_min * 60)


@router.post("/revoke", status_code=204)
def revoke_token(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """登出：撤銷 refresh token 並清除 cookie。"""
    if refresh_token:
        auth_service.revoke(db, user=user, raw_refresh_token=refresh_token, ip=client_ip(request))
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
