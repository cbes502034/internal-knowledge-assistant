"""註冊、登入、權杖更新、撤銷、由 JWT 取得使用者。（對應企劃書 圖 6 循序圖）

依賴 app.core.security（密碼雜湊、JWT、refresh token）——建議先完成那個檔案。
"""
from sqlalchemy.orm import Session

from app.models import User


def register_user(db: Session, *, email: str, password: str, dept_code: str) -> User:
    """TODO：註冊。

    1. 用 services.user.get_department_by_code 找部門；找不到 → AppError(422, "unknown_department", ...)
    2. email 是否已存在？是 → raise conflict("email_taken", "此 email 已註冊")
       （提示：也可以直接 insert，捕捉 IntegrityError；想想兩種做法在「同時註冊」時的差別）
    3. security.hash_password(password) → 建立 User(role="employee")
    4. db.add、db.commit、回傳 user
    """
    raise NotImplementedError("services.auth.register_user 尚未實作")


def login(db: Session, *, email: str, password: str, ip: str | None) -> tuple[str, str]:
    """TODO：帳密登入，回傳 (access JWT, refresh token 原文)。

    1. 以 email 找使用者
    2. 找不到、密碼錯、is_active=False → 一律 raise unauthorized("帳號或密碼錯誤")
       （為什麼三種情況要回同一個訊息？）
    3. security.create_access_token(user)
    4. security.new_refresh_token() 取得 (原文, 雜湊)；把雜湊與到期時間存進 RefreshToken
    5. 更新 user.last_active_at
    6. audit.record(db, user=user, action="login", ip=ip)
    7. 回傳 (access, refresh 原文)
    進階（P1）：連續失敗 5 次鎖定 15 分鐘
    """
    raise NotImplementedError("services.auth.login 尚未實作")


def refresh(db: Session, *, raw_refresh_token: str) -> tuple[str, str]:
    """TODO：用 refresh token 換新的 access JWT，並「輪替」refresh token。

    1. security.hash_token(raw_refresh_token) → 以雜湊找 RefreshToken
    2. 找不到、已撤銷（revoked_at 有值）、已過期 → raise unauthorized()
    3. 閒置檢查：now - user.last_active_at 超過 settings.idle_timeout_min → 撤銷並 raise unauthorized()
    4. 輪替：把舊的標記 revoked_at=now，發一個新的（同 login 的步驟 4）
       （為什麼要輪替？如果舊 token 被偷走重複使用，伺服器怎麼發現？）
    5. 回傳 (新的 access, 新的 refresh 原文)
    """
    raise NotImplementedError("services.auth.refresh 尚未實作")


def revoke(db: Session, *, user: User, raw_refresh_token: str) -> None:
    """TODO：登出／閒置。把這個 refresh token 標記為已撤銷。

    1. 以雜湊找 RefreshToken，且 user_id 必須是這位使用者
    2. 找到且尚未撤銷 → revoked_at = now；找不到就當作已完成（冪等）
    3. audit.record(db, user=user, action="logout")
    """
    raise NotImplementedError("services.auth.revoke 尚未實作")


def get_user_from_access_token(db: Session, token: str) -> User:
    """TODO：每個受保護的請求都會經過這裡（deps.get_current_user）。

    1. security.decode_access_token(token)；過期或無效 → raise unauthorized()
    2. 由 payload["sub"] 取得使用者；不存在或 is_active=False → raise unauthorized()
    3. 更新 user.last_active_at = now（閒置判斷的依據），commit
       （每個請求都寫一次資料庫，量大時怎麼改善？）
    4. 回傳 user
    """
    raise NotImplementedError("services.auth.get_user_from_access_token 尚未實作")
