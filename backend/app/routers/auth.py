"""
驗證相關的 API 端點：註冊、登入。
對應職缺：OAuth 2.0（password flow）、RESTful API 設計。
"""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.auth import TokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import login, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    """註冊：收 JSON body，回傳建好的使用者（不含 password_hash）。"""
    return register_user(db, data)


@router.post("/login", response_model=TokenResponse)
def login_endpoint(
    form: OAuth2PasswordRequestForm = Depends(),  # OAuth2 規格要求用 form 格式的 username/password，不是 JSON
    db: Session = Depends(get_db),
):
    """登入：email 填在 username 欄位，成功回傳 Bearer access token。"""
    token = login(db, form.username, form.password)
    return TokenResponse(access_token=token)
