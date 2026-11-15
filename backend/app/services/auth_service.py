"""
註冊與登入的商業邏輯。
對應職缺：OAuth 2.0 驗證機制、後端 API 開發。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.security import createAccessToken, hashPassword, verifyPassword
from app.models.user import User
from app.schemas.user import UserCreate


def register_user(db: Session, data: UserCreate) -> User:
    """建立新使用者：密碼先雜湊再存，email 違反唯一性或 dept_id 違反外鍵都會被攔截成 409。"""
    user = User(
        email=data.email,
        password_hash=hashPassword(data.password),
        dept_id=data.dept_id,
        role=data.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "此 email 已被註冊，或部門不存在")
    db.refresh(user)
    return user


def login(db: Session, email: str, password: str) -> str:
    """驗證帳密，成功則回傳一張簽好的 access token 字串。"""
    user = db.query(User).filter(User.email == email).first()

    if user is None or not verifyPassword(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號已停用")

    return createAccessToken(userId=user.id, deptId=user.dept_id, role=user.role)
