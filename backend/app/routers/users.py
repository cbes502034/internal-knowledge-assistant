"""
使用者相關的 API 端點。
對應職缺：身份驗證、各部門權限控管（RBAC）。
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    """回傳目前登入者自己的資料；同時是驗證 get_current_user 有沒有生效的最簡單端點。"""
    return current_user
