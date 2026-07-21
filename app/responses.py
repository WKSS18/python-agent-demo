"""统一 API 响应与全局异常处理。

普通 JSON 接口统一返回 ``{data, code, message}``；SSE 在连接建立后则使用 error
事件表达失败。服务端日志保留异常堆栈，浏览器只收到脱敏后的可读信息。
"""

import logging
from typing import Any, TypeVar

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas import ApiResponse


logger = logging.getLogger(__name__)
T = TypeVar("T")


def success(data: T | None = None, message: str = "success") -> ApiResponse[T]:
    """构造成功响应信封，让路由无需重复拼装通用字段。"""
    return ApiResponse(data=data, code=status.HTTP_200_OK, message=message)


def register_exception_handlers(app: FastAPI) -> None:
    """集中把框架和业务异常转换成前端稳定可解析的结构。"""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return _error_response(exc.status_code, message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        messages = [error.get("msg", "参数格式错误") for error in exc.errors()]
        return _error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(messages))

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error: %s %s", request.method, request.url.path, exc_info=exc)
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "服务器内部错误")


def _error_response(
    code: int,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """保证 HTTP 状态、业务 code 与响应内容保持一致。"""
    body = ApiResponse[Any](data=None, code=code, message=message)
    return JSONResponse(
        status_code=code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )
