"""
【檔案用途】建立（或升級）IT 管理員帳號。
註冊 API 只能建出 employee，第一位管理員只能從伺服器上用這個腳本建立（這是刻意的：
「誰能成為管理員」不該開放在網路上，只有能登入伺服器的人才能決定）。

用法（在 backend 目錄）：
    python -m scripts.create_admin admin@company.com ops
密碼會在終端機互動輸入（不顯示、不留在指令歷史裡）。
"""

import getpass  # 在終端機輸入密碼時不顯示字元
import sys  # 讀命令列參數（sys.argv）、出錯時結束程式（sys.exit）

from sqlalchemy import select  # 組 SELECT 查詢

import app.models  # noqa: F401  確保所有 model 都已登記（只 import 不使用，noqa 讓檢查工具不要警告）
from app.core.database import SessionLocal  # 開資料庫 session
from app.core.security import hashPassword  # Argon2 雜湊（你寫的）
from app.models.department import Department  # 用部門代碼查部門
from app.models.user import User, UserRole  # 使用者表與角色列舉


def main() -> None:
    """讀參數 → 查部門 → 已存在就升級，不存在就輸入密碼建立。"""
    # ── 1. 讀命令列參數：sys.argv[0] 是腳本名稱，後面才是使用者給的參數 ──
    if len(sys.argv) != 3:
        sys.exit("用法：python -m scripts.create_admin <email> <部門代碼>")
    email, dept_code = sys.argv[1], sys.argv[2]

    with SessionLocal() as db:  # with：區塊結束自動關閉 session
        # ── 2. 確認部門存在；不存在就列出可用的代碼 ──
        dept = db.scalar(select(Department).where(Department.code == dept_code))
        if dept is None:
            codes = ", ".join(db.scalars(select(Department.code)))
            sys.exit(f"部門代碼不存在；可用的有：{codes}")

        # ── 3. 帳號已存在：只升級角色並啟用，不改密碼 ──
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.role = UserRole.IT_ADMIN.value
            user.is_active = True
            db.commit()
            print(f"{email} 已升級為 IT 管理員")
            return

        # ── 4. 帳號不存在：互動輸入密碼（輸入兩次確認）──
        password = getpass.getpass("設定密碼（至少 8 字）：")
        if len(password) < 8 or password != getpass.getpass("再輸入一次："):
            sys.exit("密碼太短或兩次不一致")

        # ── 5. 建立管理員 ──
        db.add(User(email=email, password_hash=hashPassword(password), dept_id=dept.id, role=UserRole.IT_ADMIN.value))
        db.commit()
        print(f"已建立 IT 管理員 {email}")


# 直接執行這個檔案（python -m scripts.create_admin）時才跑 main；被別的檔案 import 時不會自動執行
if __name__ == "__main__":
    main()
