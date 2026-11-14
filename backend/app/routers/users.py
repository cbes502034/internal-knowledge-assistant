from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_it_admin
from app.models import User
from app.schemas import Page, UserCreate, UserOut, UserPatch
from app.services import auth as auth_service
from app.services import user as user_service

router = APIRouter(tags=["users"])


@router.post("/users", response_model=UserOut, status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """註冊（正式環境改由 AD 同步）。"""
    return auth_service.register_user(db, email=body.email, password=body.password, dept_code=body.dept_code)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=Page[UserOut])
def list_users(
    dept: str | None = Query(default=None, description="部門代碼"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    items, total = user_service.list_users(db, dept_code=dept, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int,
    body: UserPatch,
    admin: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    return user_service.update_user(db, actor=admin, user_id=user_id, patch=body)
