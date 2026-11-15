from fastapi import (
    FastAPI, 
    Depends, 
    HTTPException, 
    status
)
from app.core.config import settings
from app.core.database import get_db

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.routers import auth, users

app = FastAPI(title=settings.app_name)

app.include_router(auth.router)
app.include_router(users.router)


@app.get("/")
def test():
    return {"ok":True}

@app.get("/health")
def health():
    return {"ok":"health"}

@app.get("/get-db")
def test_db(db : Session = Depends(get_db)):
    try:
        result = db.execute(text("SELECT NOW()")).scalar()
        return {
            "status" : "success",
            "message" : f"{settings.postgres_database} 資料庫連線正常",
            "db_time" : result
        }
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"資料庫連線失敗：{str(e)}",
        )
