"""路由共用的依賴：目前使用者、角色檢查。"""
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import forbidden
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
