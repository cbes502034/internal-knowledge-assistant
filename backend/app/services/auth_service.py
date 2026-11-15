"""
【檔案用途】註冊與登入的商業邏輯（不含 HTTP 細節，HTTP 的部分在 routers）。
  register_user()  自助註冊，角色固定 employee
  authenticate()   驗證帳密，回傳 User

對應職缺：OAuth 2.0 驗證機制、後端 API 開發。
被誰呼叫：routers/users.py（註冊）、routers/auth.py（登入）。
"""

from fastapi import HTTPException, status  # 丟出帶 HTTP 狀態碼的錯誤；status 提供狀態碼常數
from sqlalchemy import select  # 組 SELECT 查詢
from sqlalchemy.exc import IntegrityError  # 違反資料庫約束（例如 email 唯一）時的例外
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.security import hashPassword, verifyPassword  # Argon2 雜湊與驗證（你寫的）
from app.models.department import Department  # 用部門代碼查部門
from app.models.user import User, UserRole  # 使用者表與角色列舉
from app.schemas.admin import RegisterRequest  # 註冊請求的格式（沒有 role 欄位）


def register_user(db: Session, data: RegisterRequest) -> User:
    """自助註冊：角色固定是 employee（不讓註冊者自己選角色），部門用代碼查。"""
    # ── 1. 部門代碼換成部門 ──
    dept = db.scalar(select(Department).where(Department.code == data.dept_code))
    if dept is None:
        # 部門不存在是「輸入值錯誤」（422），和 email 重複的「資源衝突」（409）分開回報
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "部門代碼不存在")

    # ── 2. 建立使用者：密碼先雜湊，角色寫死 employee ──
    user = User(
        email=data.email,
        password_hash=hashPassword(data.password),
        dept_id=dept.id,
        role=UserRole.EMPLOYEE.value,
    )
    db.add(user)

    # ── 3. 寫入；email 重複由資料庫的唯一約束擋下 ──
    try:
        db.commit()
    except IntegrityError:
        # 先查再寫仍可能撞到（兩個請求同時註冊同一個 email），所以最後靠資料庫的唯一約束兜底
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "此 email 已被註冊")
    db.refresh(user)  # 取得資料庫產生的 id 與預設值
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """驗證帳密，成功回傳 User；失敗一律 401。"""
    # ── 1. 用 email 找使用者 ──
    user = db.scalar(select(User).where(User.email == email))

    # ── 2. 檢查密碼 ──
    # 帳號不存在與密碼錯誤回同一句話：分開講，等於告訴攻擊者「這個 email 有註冊」
    if user is None or not verifyPassword(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")

    # ── 3. 檢查帳號是否啟用 ──
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號已停用")
    return user
