# 這個腳本的目的：灌入部門的初始資料，
# 因為 User.dept_id 是必填外鍵，沒有部門資料就建立不了任何使用者。

from app.core.database import SessionLocal
from app.models.department import Department

# code 對應職缺情境裡的六個部門；name 是顯示用的中文名稱
DEPARTMENTS = [
    ("sales", "業務"),
    ("product", "產品"),
    ("rd", "研發"),
    ("ops", "營運"),
    ("finance", "財務"),
    ("gm_office", "總經理室"),
]


def main():
    db = SessionLocal()
    try:
        for code, name in DEPARTMENTS:
            # 先查有沒有同 code 的部門，避免腳本跑第二次時重複插入、
            # 違反 department.code 的 unique 約束而噴錯
            exists = db.query(Department).filter(Department.code == code).first()
            if not exists:
                db.add(Department(code=code, name=name))
        db.commit()
        print("部門種子資料建立完成")
    finally:
        db.close()  # 不管成功或失敗都要關連線，避免連線池被占用


if __name__ == "__main__":
    main()
