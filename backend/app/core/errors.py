"""
統一錯誤格式：所有錯誤都回 {"code": ..., "message": ...}，前端只要讀 message 就能顯示。
對應職缺：RESTful API 設計。

FastAPI 預設的錯誤格式是 {"detail": ...}，而且驗證錯誤（422）的 detail 是一串結構化清單，
前端很難直接顯示；在這裡統一轉換，每個路由就不用各自處理。
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _body(code: str, message: str) -> dict:
    # 同時保留 detail：FastAPI 自帶的 /docs 介面與習慣預設格式的工具仍然讀得到
    return {"code": code, "message": message, "detail": message}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "請求失敗"
        # headers 要原樣帶回去：例如 401 的 WWW-Authenticate 是 OAuth2 規格要求的
        return JSONResponse(_body(f"http_{exc.status_code}", message), exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", []) if part not in ("body", "query", "path"))
        message = f"輸入格式錯誤：{field} {first.get('msg', '')}".strip()
        return JSONResponse(_body("validation_error", message), 422)
