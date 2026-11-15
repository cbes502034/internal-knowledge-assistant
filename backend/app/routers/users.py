"""
使用者相關的 API 端點：註冊、我的資料、使用者管理。
對應職缺：身份驗證、各部門權限控管（RBAC）、RESTful API 設計。

權限分兩層，這個檔案是第一層「路由層」：誰能呼叫這個端點（例如只有 IT 管理員能改別人的角色）。
第二層「資料層」在檢索：誰看得到哪份文件（core/retriever.py）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.schemas.admin import RegisterRequest, UserDetailResponse
from app.schemas.common import Page
from app.schemas.user import UserResponse, UserUpdate
from app.services.audit import log_event
from app.services.auth_service import register_user
from app.services.token_service import revoke_all

router = APIRouter(prefix="/api/v1", tags=["users"])

admin_only = require_role(UserRole.IT_ADMIN)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """自助註冊（不需登入）：角色固定為 employee。成功回 201 Created。"""
    user = register_user(db, data)
    log_event(db, request, "user.register", user_id=user.id, target=f"user:{user.id}")
    return user


@router.get("/me", response_model=UserDetailResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    """回傳目前登入者自己的資料（含部門名稱）。"""
    return current_user


@router.get("/users", response_model=Page[UserDetailResponse])
def list_users(
    limit: int = Query(50, ge=1, le=100),  # 上限 100：不讓一個請求把整張表撈回去
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """使用者列表（IT 管理員）。"""
    total = db.scalar(select(func.count()).select_from(User))
    items = db.scalars(select(User).order_by(User.id).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)


@router.patch("/users/{user_id}", response_model=UserDetailResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """修改使用者的角色、部門、啟用狀態（IT 管理員）。PATCH = 只改有送來的欄位。"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "使用者不存在")

    changes = data.model_dump(exclude_unset=True)  # 沒送的欄位不要覆蓋成 None

    # 不能停用或降級自己：系統只有一位管理員時，這一步會把所有人鎖在管理功能外面
    if user.id == admin.id and (
        changes.get("is_active") is False
        or ("role" in changes and changes["role"] != UserRole.IT_ADMIN.value)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "不能停用或降級自己的帳號")

    for field, value in changes.items():
        setattr(user, field, value)

    # 停用帳號時，所有 refresh token 一起作廢：否則他手上的 token 還能繼續換 access token
    if changes.get("is_active") is False:
        revoke_all(db, user.id)

    try:
        db.commit()
    except IntegrityError:
        # email 撞到別人的、或部門編號不存在：資料庫的約束擋下來
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email 已被使用，或部門不存在")
    db.refresh(user)
    log_event(db, request, "user.update", user_id=admin.id, target=f"user:{user.id}")
    return user
