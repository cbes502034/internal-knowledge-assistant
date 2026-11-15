"""
驗證相關的 API 端點：換發 token、登出。
對應職缺：OAuth 2.0（password grant 與 refresh_token grant）、RESTful API 設計。

OAuth 2.0 規格把「拿 token」統一成一個端點 /token，用 grant_type 區分方式：
  grant_type=password       用帳密換 token（登入）
  grant_type=refresh_token  用 refresh token 換新的 access token（續期）
註冊移到 POST /api/v1/users（建立一個「使用者」資源，符合 REST 的命名）。
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import createAccessToken
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services.audit import log_event
from app.services.auth_service import authenticate
from app.services.token_service import (
    RefreshTokenError,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/v1/auth"  # 只有驗證端點收得到這個 cookie，其他 API 請求不會帶著它到處跑


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=settings.refresh_token_hours * 3600,
        path=COOKIE_PATH,
        httponly=True,  # JavaScript 讀不到：就算網頁被注入惡意腳本（XSS），也偷不走它
        samesite="lax",  # 別的網站發起的跨站請求不會帶這個 cookie（防 CSRF）
        secure=settings.app_env == "production",  # 正式環境只走 HTTPS；本機開發是 http，所以先關
    )


def _token_response(user: User, raw_refresh: str) -> JSONResponse:
    access = createAccessToken(userId=user.id, deptId=user.dept_id, role=user.role)
    response = JSONResponse(TokenResponse(access_token=access).model_dump())
    _set_refresh_cookie(response, raw_refresh)
    return response


@router.post("/token", response_model=TokenResponse)
def issue_token(
    request: Request,
    grant_type: Annotated[str, Form()],
    username: Annotated[str | None, Form()] = None,  # OAuth2 規格叫 username，我們填 email
    password: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
):
    """登入或續期；access token 放在回應內容，refresh token 放在 HttpOnly cookie。"""
    if grant_type == "password":
        if not username or not password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "請輸入帳號與密碼")
        try:
            user = authenticate(db, username, password)
        except HTTPException:
            # 登入失敗也要記：短時間大量失敗就是暴力破解的跡象
            log_event(db, request, "login.failed", target=f"email:{username}")
            raise
        user.last_active_at = datetime.now(timezone.utc)
        raw = issue_refresh_token(db, user)
        db.commit()
        log_event(db, request, "login.success", user_id=user.id)
        return _token_response(user, raw)

    if grant_type == "refresh_token":
        try:
            if not refresh_token:
                raise RefreshTokenError("尚未登入")
            user, raw = rotate_refresh_token(db, refresh_token)
        except RefreshTokenError as e:
            # 失敗時順便清掉瀏覽器上的壞 cookie；這裡要自己組回應，丟 HTTPException 的話刪 cookie 的指令會遺失
            response = JSONResponse({"code": "invalid_grant", "message": str(e)}, status.HTTP_401_UNAUTHORIZED)
            response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
            return response
        return _token_response(user, raw)

    raise HTTPException(status.HTTP_400_BAD_REQUEST, "不支援的 grant_type")


@router.post("/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke(
    request: Request,
    refresh_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
):
    """
    登出：作廢 refresh token 並清掉 cookie。
    不要求 access token：閒置登出時 access token 往往已經過期，仍然要能登出。
    """
    if refresh_token:
        user_id = revoke_refresh_token(db, refresh_token)
        if user_id is not None:
            log_event(db, request, "logout", user_id=user_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return response
