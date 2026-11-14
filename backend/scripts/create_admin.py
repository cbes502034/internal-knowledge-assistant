"""建立 IT 管理員，或把既有帳號升級成 IT 管理員。

執行（在 backend/ 下）：
  python -m scripts.create_admin --email it@example.com --dept gm_office
密碼會在終端機提示輸入（不會顯示、不會留在指令歷史）。
自動化環境可改用環境變數：ADMIN_PASSWORD=... python -m scripts.create_admin --email ... --password-env ADMIN_PASSWORD
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core import security
from app.db import SessionLocal
from app.models import User
from app.services import user as user_service


def main() -> None:
    parser = argparse.ArgumentParser(description="建立或升級 IT 管理員")
    parser.add_argument("--email", required=True)
    parser.add_argument("--dept", default="gm_office", help="部門代碼（預設 gm_office）")
    parser.add_argument("--password-env", help="從這個環境變數讀密碼，而不是互動輸入")
    args = parser.parse_args()

    with SessionLocal() as db:
        email = args.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.role = "it_admin"
            user.is_active = True
            db.commit()
            print(f"已將 {email} 升級為 IT 管理員")
            return

        password = os.environ.get(args.password_env, "") if args.password_env else getpass.getpass("密碼（至少 8 字元）：")
        if len(password) < 8:
            sys.exit("密碼至少 8 個字元")
        department = user_service.get_department_by_code(db, args.dept)
        if department is None:
            sys.exit(f"找不到部門 {args.dept}，請先執行 python -m scripts.seed")
        db.add(User(email=email, password_hash=security.hash_password(password), dept_id=department.id,
                    role="it_admin"))
        db.commit()
        print(f"已建立 IT 管理員 {email}（{department.name}）")


if __name__ == "__main__":
    main()
