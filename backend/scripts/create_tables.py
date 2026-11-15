# 這個腳本的唯一目的：把 app/models 裡定義的 ORM model，
# 轉成 Postgres 裡真正存在的資料表（執行一次 DDL）。

import app.models  # 只是 import，不直接用到裡面的名稱；
                   # 但這行是必要的——Python 要先執行過 user.py、department.py
                   # 裡面的 class 定義，SQLAlchemy 才會把它們登記到 Base.metadata 裡。
                   # 如果不 import，create_all 會以為專案裡什麼表都沒定義過。

from app.core.database import Base, engine


def main():
    # create_all 會檢查 Base.metadata 裡登記的每個 model，
    # 對還不存在的表發出 CREATE TABLE；已存在的表不會重複建立或報錯。
    Base.metadata.create_all(bind=engine)
    print("資料表建立完成")


if __name__ == "__main__":
    main()
