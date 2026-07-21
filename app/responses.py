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
    body = ApiResponse[Any](data=None, code=code, message=message)
    return JSONResponse(
        status_code=code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )
