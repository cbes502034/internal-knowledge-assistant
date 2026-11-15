"""
註冊與登入的商業邏輯。
對應職缺：OAuth 2.0 驗證機制、後端 API 開發。
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hashPassword, verifyPassword
from app.models.department import Department
from app.models.user import User, UserRole
from app.schemas.admin import RegisterRequest


def register_user(db: Session, data: RegisterRequest) -> User:
    """自助註冊：角色固定是 employee（不讓註冊者自己選角色），部門用代碼查。"""
    dept = db.scalar(select(Department).where(Department.code == data.dept_code))
    if dept is None:
        # 部門不存在是「輸入值錯誤」（422），和 email 重複的「資源衝突」（409）分開回報
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "部門代碼不存在")

    user = User(
        email=data.email,
        password_hash=hashPassword(data.password),
        dept_id=dept.id,
        role=UserRole.EMPLOYEE.value,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 先查再寫仍可能撞到（兩個請求同時註冊同一個 email），所以最後靠資料庫的唯一約束兜底
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "此 email 已被註冊")
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """驗證帳密，成功回傳 User；失敗一律 401。"""
    user = db.scalar(select(User).where(User.email == email))

    # 帳號不存在與密碼錯誤回同一句話：分開講，等於告訴攻擊者「這個 email 有註冊」
    if user is None or not verifyPassword(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號已停用")
    return user
