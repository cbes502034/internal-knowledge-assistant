"""統一錯誤格式：{"code": 程式判斷用, "message": 顯示用}，不回傳內部例外細節。"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def not_found(message: str = "找不到資源") -> AppError:
    return AppError(404, "not_found", message)


def unauthorized(message: str = "請重新登入") -> AppError:
    return AppError(401, "unauthorized", message, {"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "權限不足") -> AppError:
    return AppError(403, "forbidden", message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 429: "rate_limited"}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse({"code": exc.code, "message": exc.message}, exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
        return JSONResponse({"code": code, "message": str(exc.detail)}, exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "reason": e["msg"]} for e in exc.errors()]
        return JSONResponse({"code": "validation_error", "message": "欄位驗證失敗", "fields": fields}, 422)

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_: Request, exc: NotImplementedError):
        # 骨架階段：尚未實作的業務邏輯統一回 501，訊息指出是哪個函式
        return JSONResponse({"code": "not_implemented", "message": str(exc) or "尚未實作"}, 501)
