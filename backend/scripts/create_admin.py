"""
建立（或升級）IT 管理員帳號。註冊 API 只能建出 employee，第一位管理員只能從伺服器上用這個腳本建立。

用法（在 backend 目錄）：
    python -m scripts.create_admin admin@company.test ops
密碼會在終端機互動輸入（不顯示、不留在指令歷史裡）。
"""

import getpass
import sys

from sqlalchemy import select

import app.models  # noqa: F401  確保所有 model 都已登記
from app.core.database import SessionLocal
from app.core.security import hashPassword
from app.models.department import Department
from app.models.user import User, UserRole


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("用法：python -m scripts.create_admin <email> <部門代碼>")
    email, dept_code = sys.argv[1], sys.argv[2]

    with SessionLocal() as db:
        dept = db.scalar(select(Department).where(Department.code == dept_code))
        if dept is None:
            codes = ", ".join(db.scalars(select(Department.code)))
            sys.exit(f"部門代碼不存在；可用的有：{codes}")

        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            # 已存在就只升級角色，不改密碼
            user.role = UserRole.IT_ADMIN.value
            user.is_active = True
            db.commit()
            print(f"{email} 已升級為 IT 管理員")
            return

        password = getpass.getpass("設定密碼（至少 8 字）：")
        if len(password) < 8 or password != getpass.getpass("再輸入一次："):
            sys.exit("密碼太短或兩次不一致")

        db.add(User(email=email, password_hash=hashPassword(password), dept_id=dept.id, role=UserRole.IT_ADMIN.value))
        db.commit()
        print(f"已建立 IT 管理員 {email}")


if __name__ == "__main__":
    main()
