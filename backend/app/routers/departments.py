"""
【檔案用途】部門清單 API：註冊頁的下拉選單要用，所以不需要登入。

端點：
  GET /api/v1/departments  所有部門（依編號排序）
"""

from fastapi import APIRouter, Depends  # 端點分組、依賴注入
from sqlalchemy import select  # 組 SELECT 查詢
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.database import get_db  # 依賴：每個請求一個資料庫 session
from app.models.department import Department  # 部門表
from app.schemas.department import DepartmentResponse  # 你寫的部門回應格式 {id, code, name}

router = APIRouter(prefix="/api/v1", tags=["departments"])


@router.get("/departments", response_model=list[DepartmentResponse])
def list_departments(db: Session = Depends(get_db)):
    """回傳所有部門；部門只有幾筆，不需要分頁。"""
    # scalars(...).all()：取出每一列的第一個欄位（這裡是 Department 物件）成為清單
    return db.scalars(select(Department).order_by(Department.id)).all()
