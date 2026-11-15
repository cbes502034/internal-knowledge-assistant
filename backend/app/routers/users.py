"""
【檔案用途】使用者相關的 API 端點：註冊、我的資料、使用者管理。
對應職缺：身份驗證、各部門權限控管（RBAC）、RESTful API 設計。

權限分兩層，這個檔案是第一層「路由層」：誰能呼叫這個端點（例如只有 IT 管理員能改別人的角色）。
第二層「資料層」在檢索：誰看得到哪份文件（core/retriever.py）。

端點：
  POST  /api/v1/users            註冊（免登入）
  GET   /api/v1/me               我的資料（要登入）
  GET   /api/v1/users            使用者列表（IT 管理員）
  PATCH /api/v1/users/{user_id}  修改角色、部門、啟用狀態（IT 管理員）
"""

# APIRouter：端點分組；Depends：依賴注入；HTTPException：丟錯誤；
# Query：宣告查詢字串參數的限制（例如 ?limit=50 的上下限）；Request：取 IP 寫稽核；status：狀態碼常數
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select  # func.count() 算總筆數；select 組查詢
from sqlalchemy.exc import IntegrityError  # 違反唯一約束或外鍵時的例外
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.database import get_db  # 依賴：每個請求一個資料庫 session
from app.core.deps import get_current_user, require_role  # 依賴：取得登入者、限制角色
from app.models.user import User, UserRole  # 使用者表與角色列舉
from app.schemas.admin import RegisterRequest, UserDetailResponse  # 註冊格式、含部門的使用者回應
from app.schemas.common import Page  # 分頁回應 {items, total}
from app.schemas.user import UserResponse, UserUpdate  # 你寫的使用者回應與修改格式
from app.services.audit import log_event  # 寫稽核紀錄
from app.services.auth_service import register_user  # 註冊的商業邏輯
from app.services.token_service import revoke_all  # 停用帳號時作廢所有 token

router = APIRouter(prefix="/api/v1", tags=["users"])

# 先產生好「只允許 IT 管理員」的依賴，下面多個端點共用
admin_only = require_role(UserRole.IT_ADMIN)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """自助註冊（不需登入）：角色固定為 employee。成功回 201 Created。"""
    user = register_user(db, data)
    log_event(db, request, "user.register", user_id=user.id, target=f"user:{user.id}")
    # response_model=UserResponse：FastAPI 只會輸出 UserResponse 有的欄位，password_hash 不會外流
    return user


@router.get("/me", response_model=UserDetailResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    """回傳目前登入者自己的資料（含部門名稱）。"""
    # get_current_user 已經驗證過 token 並查出 User；department 由 ORM 關聯自動載入
    return current_user


@router.get("/users", response_model=Page[UserDetailResponse])
def list_users(
    limit: int = Query(50, ge=1, le=100),  # 上限 100：不讓一個請求把整張表撈回去
    offset: int = Query(0, ge=0),  # 跳過幾筆：第二頁就是 offset=50
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),  # 底線：只要這個依賴擋人，不需要用到它的值
):
    """使用者列表（IT 管理員）。"""
    total = db.scalar(select(func.count()).select_from(User))  # 全部筆數（給前端顯示「共 N 筆」）
    items = db.scalars(select(User).order_by(User.id).limit(limit).offset(offset)).all()  # 這一頁的資料
    return Page(items=items, total=total)


@router.patch("/users/{user_id}", response_model=UserDetailResponse)
def update_user(
    user_id: int,  # 路徑參數：網址裡的 {user_id}
    data: UserUpdate,  # JSON body
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),  # 這裡要用到管理員本人（檢查是不是改自己）
):
    """修改使用者的角色、部門、啟用狀態（IT 管理員）。PATCH = 只改有送來的欄位。"""
    # ── 1. 找目標使用者 ──
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "使用者不存在")

    # ── 2. 只取「有送來」的欄位 ──
    changes = data.model_dump(exclude_unset=True)  # 沒送的欄位不要覆蓋成 None

    # ── 3. 保護：不能停用或降級自己 ──
    # 系統只有一位管理員時，這一步會把所有人鎖在管理功能外面
    if user.id == admin.id and (
        changes.get("is_active") is False
        or ("role" in changes and changes["role"] != UserRole.IT_ADMIN.value)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "不能停用或降級自己的帳號")

    # ── 4. 套用變更 ──
    for field, value in changes.items():
        setattr(user, field, value)  # 等同 user.role = value 之類，用欄位名稱字串動態設定

    # ── 5. 停用帳號時，所有 refresh token 一起作廢 ──
    # 否則他手上的 token 還能繼續換 access token
    if changes.get("is_active") is False:
        revoke_all(db, user.id)

    # ── 6. 寫入；違反約束轉成 409 ──
    try:
        db.commit()
    except IntegrityError:
        # email 撞到別人的、或部門編號不存在：資料庫的約束擋下來
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email 已被使用，或部門不存在")
    db.refresh(user)
    log_event(db, request, "user.update", user_id=admin.id, target=f"user:{user.id}")
    return user
