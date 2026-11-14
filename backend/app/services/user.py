"""部門與使用者管理。list_departments 是完整範例，其餘為 TODO。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, User
from app.schemas import UserPatch


def list_departments(db: Session) -> list[Department]:
    """【完整範例】查詢全部部門，依編號排序。"""
    return list(db.scalars(select(Department).order_by(Department.id)))


def get_department_by_code(db: Session, code: str) -> Department | None:
    """【完整範例】以代碼找部門；找不到回 None，由呼叫端決定要丟什麼錯。"""
    return db.scalar(select(Department).where(Department.code == code))


def list_users(db: Session, *, dept_code: str | None, limit: int, offset: int) -> tuple[list[User], int]:
    """TODO：使用者列表（分頁、可依部門篩選）。回傳 (這一頁的使用者, 總筆數)。

    1. 建立基本查詢 select(User)
    2. 有 dept_code 時 join Department 並加上條件
    3. 總筆數：提示 select(func.count()).select_from(查詢.subquery())
    4. 這一頁：order_by(User.id).limit(limit).offset(offset)
    """
    raise NotImplementedError("services.user.list_users 尚未實作")


def update_user(db: Session, *, actor: User, user_id: int, patch: UserPatch) -> User:
    """TODO：IT 修改使用者的部門、角色、啟用狀態。

    1. db.get(User, user_id)；不存在 → raise not_found()
    2. patch.dept_code 有值 → 用 get_department_by_code 找部門；找不到 → AppError(422, ...)
    3. 只更新 patch 中「不是 None」的欄位（提示：patch.model_dump(exclude_none=True)）
    4. 思考：IT 可以把自己的 is_active 改成 False 嗎？要不要擋？
    5. db.commit()，並呼叫 audit.record(db, user=actor, action="user.update", target=f"user:{user_id}")
    """
    raise NotImplementedError("services.user.update_user 尚未實作")
