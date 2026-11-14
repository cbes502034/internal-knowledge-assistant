"""完整範例：路由 → 服務 → 資料庫 的一條垂直切面，其他端點照這個樣子寫。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import DepartmentOut
from app.services import user as user_service

router = APIRouter(tags=["departments"])


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    """部門列表（註冊畫面的下拉選單用，不需登入）。"""
    return user_service.list_departments(db)
