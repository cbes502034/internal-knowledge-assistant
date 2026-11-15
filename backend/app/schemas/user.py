from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


UserRoleType = Literal["employee", "manager", "it_admin"]

# 1. UserCreate：建立使用者時允許提交的資料
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    dept_id: int
    role: UserRoleType = "employee"

# UserUpdate：修改使用者時允許更新的資料。
class UserUpdate(BaseModel):
    email: EmailStr | None = None
    dept_id: int | None = None
    role: UserRoleType | None = None
    is_active: bool | None = None

# UserResponse：後端回傳給前端的使用者資料。
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    dept_id: int
    role: UserRoleType
    is_active: bool
    last_active_at: datetime | None = None