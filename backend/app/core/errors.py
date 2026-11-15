"""
【檔案用途】統一錯誤格式：所有錯誤都回 {"code": ..., "message": ...}，前端只要讀 message 就能顯示。
對應職缺：RESTful API 設計。

FastAPI 預設的錯誤格式是 {"detail": ...}，而且驗證錯誤（422）的 detail 是一串結構化清單，
前端很難直接顯示；在這裡統一轉換，每個路由就不用各自處理。

被誰呼叫：main.py 的 register_error_handlers(app)。
"""

from fastapi import FastAPI, HTTPException, Request  # 應用程式物件、HTTP 錯誤類別、請求物件
from fastapi.exceptions import RequestValidationError  # 請求格式不符（Pydantic 驗證失敗）時 FastAPI 丟出的例外
from fastapi.responses import JSONResponse  # 自己組 JSON 回應


def _body(code: str, message: str) -> dict:
    """組出統一的錯誤內容。"""
    # 同時保留 detail：FastAPI 自帶的 /docs 介面與習慣預設格式的工具仍然讀得到
    return {"code": code, "message": message, "detail": message}


def register_error_handlers(app: FastAPI) -> None:
    """把兩種錯誤的處理方式註冊到 app 上；之後任何路由丟出這兩種例外，都會經過這裡。"""

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        """處理路由裡 raise HTTPException(...) 的錯誤（401、403、404、409…）。"""
        message = exc.detail if isinstance(exc.detail, str) else "請求失敗"
        # headers 要原樣帶回去：例如 401 的 WWW-Authenticate 是 OAuth2 規格要求的
        return JSONResponse(_body(f"http_{exc.status_code}", message), exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """處理請求格式錯誤（422）：只取第一個錯誤，轉成一句人看得懂的話。"""
        first = exc.errors()[0] if exc.errors() else {}
        # loc 例如 ("body", "email")：去掉 body/query/path 這種來源標記，只留欄位名稱
        field = ".".join(str(part) for part in first.get("loc", []) if part not in ("body", "query", "path"))
        message = f"輸入格式錯誤：{field} {first.get('msg', '')}".strip()
        return JSONResponse(_body("validation_error", message), 422)
