"""部門清單：註冊頁的下拉選單要用，所以不需要登入。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.department import Department
from app.schemas.department import DepartmentResponse

router = APIRouter(prefix="/api/v1", tags=["departments"])


@router.get("/departments", response_model=list[DepartmentResponse])
def list_departments(db: Session = Depends(get_db)):
    return db.scalars(select(Department).order_by(Department.id)).all()
