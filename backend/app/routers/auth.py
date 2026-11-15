"""
【檔案用途】驗證相關的 API 端點：換發 token（登入、續期）、登出。
對應職缺：OAuth 2.0（password grant 與 refresh_token grant）、RESTful API 設計。

OAuth 2.0 規格把「拿 token」統一成一個端點 /token，用 grant_type 區分方式：
  grant_type=password       用帳密換 token（登入）
  grant_type=refresh_token  用 refresh token 換新的 access token（續期）
註冊移到 POST /api/v1/users（建立一個「使用者」資源，符合 REST 的命名）。

端點：
  POST /api/v1/auth/token   登入或續期
  POST /api/v1/auth/revoke  登出
"""

from datetime import datetime, timezone  # 登入時更新 last_active_at
from typing import Annotated  # Annotated[型別, 額外資訊]：告訴 FastAPI 這個參數從哪裡來（Form、Cookie…）

from fastapi import (
    APIRouter,  # 把一組相關端點打包，main.py 再用 include_router 掛上去
    Cookie,  # 參數來源：從請求的 cookie 讀
    Depends,  # 依賴注入：例如 Depends(get_db) 會自動給一個資料庫 session
    Form,  # 參數來源：從 form 格式（application/x-www-form-urlencoded）讀；OAuth2 規格要求用 form
    HTTPException,  # 丟出帶狀態碼的錯誤
    Request,  # 原始請求物件（寫稽核時取 IP）
    Response,  # 自己組回應（登出要回 204 並刪 cookie）
    status,  # 狀態碼常數
)
from fastapi.responses import JSONResponse  # 自己組 JSON 回應（需要同時設定 cookie 時用）
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.config import settings  # 讀 refresh token 有效時數、執行環境
from app.core.database import get_db  # 依賴：每個請求一個資料庫 session
from app.core.security import createAccessToken  # 簽發 JWT access token（你寫的）
from app.models.user import User  # 型別註記
from app.schemas.auth import TokenResponse  # 回應格式 {access_token, token_type}
from app.services.audit import log_event  # 寫稽核紀錄
from app.services.auth_service import authenticate  # 驗證帳密
from app.services.token_service import (
    RefreshTokenError,  # refresh token 無效時的例外
    issue_refresh_token,  # 簽發新的 refresh token
    revoke_refresh_token,  # 登出：作廢 token
    rotate_refresh_token,  # 續期：舊換新
)

# prefix：這個 router 裡所有路徑的共同前綴；tags：在 /docs 頁面上的分組名稱
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/v1/auth"  # 只有驗證端點收得到這個 cookie，其他 API 請求不會帶著它到處跑


def _set_refresh_cookie(response: Response, raw: str) -> None:
    """把 refresh token 放進回應的 Set-Cookie 標頭，並設定安全屬性。"""
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=settings.refresh_token_hours * 3600,  # 秒數；到期後瀏覽器自動丟掉
        path=COOKIE_PATH,
        httponly=True,  # JavaScript 讀不到：就算網頁被注入惡意腳本（XSS），也偷不走它
        samesite="lax",  # 別的網站發起的跨站請求不會帶這個 cookie（防 CSRF）
        secure=settings.app_env == "production",  # 正式環境只走 HTTPS；本機開發是 http，所以先關
    )


def _token_response(user: User, raw_refresh: str) -> JSONResponse:
    """組出登入／續期成功的回應：內容放 access token，cookie 放 refresh token。"""
    access = createAccessToken(userId=user.id, deptId=user.dept_id, role=user.role)
    response = JSONResponse(TokenResponse(access_token=access).model_dump())  # model_dump：Pydantic 物件轉 dict
    _set_refresh_cookie(response, raw_refresh)
    return response


@router.post("/token", response_model=TokenResponse)
def issue_token(
    request: Request,
    grant_type: Annotated[str, Form()],
    username: Annotated[str | None, Form()] = None,  # OAuth2 規格叫 username，我們填 email
    password: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Cookie()] = None,  # 參數名稱就是 cookie 名稱
    db: Session = Depends(get_db),
):
    """登入或續期；access token 放在回應內容，refresh token 放在 HttpOnly cookie。"""
    # ── 情況一：帳密登入 ──
    if grant_type == "password":
        if not username or not password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "請輸入帳號與密碼")
        try:
            user = authenticate(db, username, password)
        except HTTPException:
            # 登入失敗也要記：短時間大量失敗就是暴力破解的跡象
            log_event(db, request, "login.failed", target=f"email:{username}")
            raise  # 原本的 401 照樣丟給前端
        # 登入成功：更新最後活動時間、簽發 refresh token、記稽核
        user.last_active_at = datetime.now(timezone.utc)
        raw = issue_refresh_token(db, user)
        db.commit()
        log_event(db, request, "login.success", user_id=user.id)
        return _token_response(user, raw)

    # ── 情況二：用 refresh token 續期 ──
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

    # ── 其他 grant_type 一律不支援 ──
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
    # ── 有 cookie 才作廢；作廢成功才記稽核 ──
    if refresh_token:
        user_id = revoke_refresh_token(db, refresh_token)
        if user_id is not None:
            log_event(db, request, "logout", user_id=user_id)

    # ── 不管有沒有 cookie，都回 204 並要求瀏覽器刪掉 cookie ──
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return response
