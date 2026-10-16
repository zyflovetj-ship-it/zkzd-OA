"""类型化错误体系 + 全局异常处理，客户端只看到规范化错误结构。"""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _error_body(code: str, message: str, details=None):
    return {"error": {"code": code, "message": message, "details": details}}


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error"

    def __init__(self, message=None, *, code=None, status_code=None, details=None):
        if message:
            self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "资源不存在"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "资源冲突"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "需要登录"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "没有权限"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "校验失败"


async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.details),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body("http_error", str(exc.detail)),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=_error_body("validation_error", "校验失败", exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    from app.core.logging import get_logger

    logger = get_logger("errors")
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_error", "服务器内部错误"),
    )
