"""统一错误结构与异常。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务错误，携带稳定错误码，不泄露堆栈。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        # 不把堆栈泄露给客户端；堆栈只进服务端日志。
        return JSONResponse(status_code=500, content=error_body("internal_error", "服务器内部错误"))
