"""
【檔案用途】註冊、使用者管理、文件管理、稽核的請求與回應格式。
  RegisterRequest     自助註冊（沒有 role 欄位）
  UserDetailResponse  使用者資料＋部門
  DocumentPatch       管理員修改文件
  AuditLogResponse    一筆稽核紀錄

另外開一個檔案，而不是改你寫的 schemas/user.py、document.py：你的檔案保持原樣，這裡只「擴充」。
"""

from datetime import date, datetime  # 型別：生效日、建立時間
from typing import Literal  # 限定值

# EmailStr：自動驗證 email 格式；IPvAnyAddress：IPv4 或 IPv6 位址型別
from pydantic import BaseModel, ConfigDict, EmailStr, Field, IPvAnyAddress

from app.schemas.department import DepartmentResponse  # 你寫的部門格式（巢狀放進使用者回應）
from app.schemas.document import DocumentLevel  # 你寫的文件等級 Literal（public / dept / restricted）
from app.schemas.user import UserResponse  # 你寫的使用者回應（這裡繼承它再加欄位）


class RegisterRequest(BaseModel):
    """
    自助註冊只收 email、密碼、部門代碼。
    刻意「沒有 role 欄位」：如果讓註冊者自己填角色，任何人都能註冊成 it_admin（權限提升漏洞）。
    角色只能由 IT 管理員事後調整。
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)  # 至少 8 字；上限避免超長字串拖慢 Argon2
    dept_code: str = Field(min_length=1, max_length=20)  # 前端下拉選單送的是部門代碼，不是編號


class UserDetailResponse(UserResponse):
    """比 UserResponse 多帶部門名稱，前端顯示「運營 · 依權限檢索」要用。"""
    department: DepartmentResponse  # 從 User.department 關聯讀出


class DocumentPatch(BaseModel):
    """
    管理員可修改的文件欄位，全部選填（PATCH 只改有送的）。status 只允許改成 deprecated：
    ready 只能由處理流程設定（代表 chunk 都已寫好），手動改成 ready 會讓沒處理完的文件被檢索到。
    """
    title: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=30)
    level: DocumentLevel | None = None
    effective_date: date | None = None
    status: Literal["deprecated"] | None = None


class AuditLogResponse(BaseModel):
    """一筆稽核紀錄。"""
    model_config = ConfigDict(from_attributes=True)  # 可直接用 ORM 物件建立

    id: int
    user_id: int | None
    action: str
    target: str | None
    ip: IPvAnyAddress | None  # 資料庫 INET 欄位讀出來是 IP 物件，輸出時轉成字串
    created_at: datetime
