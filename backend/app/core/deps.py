"""
驗證守門員：把「請求帶來的 token」換成「資料庫裡真正的 User 物件」，並提供角色檢查。
對應職缺：OAuth 2.0 / JWT 驗證、各部門權限控管（RBAC）。

其他路由只要宣告 Depends(get_current_user)，就能直接拿到已驗證的使用者。
"""

from datetime import datetime, timezone

import jwt  # PyJWT：解碼並驗證 JWT 的簽名與有效期
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import oauth2_scheme, decodeAccessToken
from app.models.user import User, UserRole


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
    """產生「只允許指定角色通過」的 dependency，例如 Depends(require_role(UserRole.IT_ADMIN))。"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in [r.value for r in allowed_roles]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "權限不足")
        return user

    return checker
