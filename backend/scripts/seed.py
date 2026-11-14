"""種子資料：建立部門。可重複執行（已存在的不會重複新增）。

執行：在 backend/ 下  python -m scripts.seed
"""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Department

DEPARTMENTS = [
    ("sales", "業務體系"),
    ("product", "產品發展體系"),
    ("rd", "研發單位"),
    ("ops", "運營單位"),
    ("finance", "財務單位"),
    ("gm_office", "總經理室"),
]


def main() -> None:
    with SessionLocal() as db:
        existing = set(db.scalars(select(Department.code)))
        added = [Department(code=code, name=name) for code, name in DEPARTMENTS if code not in existing]
        db.add_all(added)
        db.commit()
        print(f"部門：新增 {len(added)} 筆，原有 {len(existing)} 筆")


if __name__ == "__main__":
    main()
