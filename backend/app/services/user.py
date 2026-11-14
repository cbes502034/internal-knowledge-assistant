"""部門與使用者管理。"""
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import AppError, not_found
from app.models import Department, RefreshToken, User
from app.schemas import UserPatch
from app.services import audit


def list_departments(db: Session) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.id)))


def get_department_by_code(db: Session, code: str) -> Department | None:
    """以代碼找部門；找不到回 None，由呼叫端決定要丟什麼錯。"""
    return db.scalar(select(Department).where(Department.code == code))


def require_department(db: Session, code: str) -> Department:
    department = get_department_by_code(db, code)
    if department is None:
        raise AppError(422, "unknown_department", "部門不存在")
    return department


def list_users(db: Session, *, dept_code: str | None, limit: int, offset: int) -> tuple[list[User], int]:
    """使用者列表（分頁、可依部門篩選）。回傳 (這一頁, 總筆數)。"""
    query = select(User)
    if dept_code:
        query = query.join(Department, Department.id == User.dept_id).where(Department.code == dept_code)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(User.id).limit(limit).offset(offset)).unique()
    return list(items), total


def revoke_all_tokens(db: Session, user_id: int) -> None:
    """撤銷某人所有尚未撤銷的 refresh token（停用帳號、偵測到權杖被重複使用時）。"""
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def update_user(db: Session, *, actor: User, user_id: int, patch: UserPatch) -> User:
    """IT 修改使用者的部門、角色、啟用狀態。"""
    user = db.get(User, user_id)
    if user is None:
        raise not_found("找不到使用者")
    changes = patch.model_dump(exclude_none=True)

    # 不允許 IT 停用或降級自己：避免最後一位管理員把自己鎖在門外
    if user.id == actor.id and (changes.get("is_active") is False or changes.get("role", "it_admin") != "it_admin"):
        raise AppError(422, "self_modification", "不能停用或降級自己的帳號")

    if "dept_code" in changes:
        user.dept_id = require_department(db, changes.pop("dept_code")).id
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False:
        revoke_all_tokens(db, user.id)        # 停用後立刻失效，不等權杖過期

    audit.record(db, user=actor, action="user.update", target=f"user:{user.id}")
    db.commit()
    db.refresh(user)
    return user
