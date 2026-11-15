# 這個腳本的唯一目的：把 app/models 裡定義的 ORM model，
# 轉成 Postgres 裡真正存在的資料表（執行一次 DDL）。

import app.models  # 只是 import，不直接用到裡面的名稱；
                   # 但這行是必要的——Python 要先執行過 user.py、department.py
                   # 裡面的 class 定義，SQLAlchemy 才會把它們登記到 Base.metadata 裡。
                   # 如果不 import，create_all 會以為專案裡什麼表都沒定義過。

from sqlalchemy import text

from app.core.database import Base, engine


def main():
    # 先啟用 pgvector 擴充：document_chunks 有 vector 型別的欄位，
    # 沒有這個擴充，建表時資料庫會不認得 vector 型別（每個資料庫只需要啟用一次）
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # create_all 會檢查 Base.metadata 裡登記的每個 model，
    # 對還不存在的表發出 CREATE TABLE；已存在的表不會重複建立或報錯。
    Base.metadata.create_all(bind=engine)
    print("資料表建立完成")


if __name__ == "__main__":
    main()
