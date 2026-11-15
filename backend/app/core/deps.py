"""
【檔案用途】驗證守門員：把「請求帶來的 token」換成「資料庫裡真正的 User 物件」，並提供角色檢查。
對應職缺：OAuth 2.0 / JWT 驗證、各部門權限控管（RBAC）。

其他路由只要宣告 Depends(get_current_user)，就能直接拿到已驗證的使用者：
  get_current_user()     任何登入者都能過
  require_role(角色...)  只有指定角色能過（回傳一個 dependency）

請求進來的順序：oauth2_scheme 取 token → get_current_user 驗證 → require_role 檢查角色 → 路由函式
"""

from datetime import datetime, timezone  # 更新 last_active_at 用（UTC 時間）

import jwt  # PyJWT：解碼並驗證 JWT 的簽名與有效期
from fastapi import Depends, HTTPException, status  # 依賴注入、丟錯誤、狀態碼常數
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.database import get_db  # 依賴：資料庫 session
# oauth2_scheme：從 Authorization: Bearer <token> 標頭取出 token；decodeAccessToken：驗證並解開 JWT（你寫的）
from app.core.security import oauth2_scheme, decodeAccessToken
from app.models.user import User, UserRole  # 使用者表與角色列舉


def get_current_user(
    token: str = Depends(oauth2_scheme),  # 自動從 Authorization: Bearer <token> 取出 token
    db: Session = Depends(get_db),
) -> User:
    """驗證 token -> 查使用者 -> 確認帳號啟用中 -> 更新最後活動時間，回傳 User。"""
    # 第一關：token 有沒有被竄改、有沒有過期
    try:
        payload = decodeAccessToken(token)
    except jwt.ExpiredSignatureError:
        # 必須先抓這個子類別，才能把「過期」與「無效」分開提示
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登入已過期，請重新登入")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "無效的憑證")

    # 第二關：token 是真的，但使用者現在還存在、還啟用嗎？（簽發後可能被刪除或停用）
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號不存在或已停用")

    # 第三關：記錄這次驗證通過的時間
    user.last_active_at = datetime.now(timezone.utc)
    db.commit()

    return user


def require_role(*allowed_roles: UserRole):
    """
    產生「只允許指定角色通過」的 dependency，例如 Depends(require_role(UserRole.IT_ADMIN))。
    這種「回傳函式的函式」叫 dependency factory：角色清單在外層傳入，內層 checker 才是 FastAPI 真正呼叫的依賴。
    """

    def checker(user: User = Depends(get_current_user)) -> User:
        """先經過 get_current_user（沒登入就 401），再檢查角色（角色不符就 403）。"""
        # allowed_roles 是列舉，user.role 是字串，所以比對前先取出列舉的 .value
        if user.role not in [r.value for r in allowed_roles]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "權限不足")
        return user

    return checker  # 回傳的是函式本身（不是呼叫結果），交給 Depends 使用
