"""FastAPI 全局异常处理器

为所有自定义异常和标准 Python 异常注册 FastAPI exception handler，
返回统一结构的 JSON 响应。
"""

import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from bin.integrated_app.exceptions import RestoreError

logger = logging.getLogger(__name__)


def _build_error_body(exc: RestoreError) -> dict:
    """构建统一错误响应体"""
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        }
    }


def _is_htmx_request(request: Request) -> bool:
    """判断请求是否来自 HTMX"""
    return request.headers.get("HX-Request") == "true"


def _htmx_error_response(message: str, status: int = 400) -> Response:
    """为 HTMX 请求返回带 HX-Trigger 的错误响应，触发前端 Toast"""
    return Response(
        status_code=status,
        headers={
            "HX-Trigger": json.dumps(
                {"showToast": {"message": message, "type": "error"}},
                ensure_ascii=False,
            )
        },
    )


async def _restore_error_handler(request: Request, exc: RestoreError):
    """处理所有 RestoreError 子类异常"""
    status = exc.http_status()
    logger.warning("RestoreError [%s] %s — %s", exc.code, exc.message, exc.detail)
    if _is_htmx_request(request):
        return _htmx_error_response(exc.message, status)
    return JSONResponse(status_code=status, content=_build_error_body(exc))


async def _value_error_handler(request: Request, exc: ValueError):
    """将 ValueError 包装为结构化响应"""
    logger.warning("ValueError: %s", exc)
    message = str(exc)
    if _is_htmx_request(request):
        return _htmx_error_response(message, 422)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALUE_ERROR",
                "message": message,
                "detail": {},
            }
        },
    )


async def _memory_error_handler(request: Request, exc: MemoryError):
    """将 MemoryError 包装为结构化响应"""
    logger.error("MemoryError: %s", exc)
    message = "系统内存不足，请尝试降低分辨率或缩小输入尺寸"
    if _is_htmx_request(request):
        return _htmx_error_response(message, 422)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INSUFFICIENT_RAM",
                "message": message,
                "detail": {},
            }
        },
    )


async def _file_not_found_error_handler(request: Request, exc: FileNotFoundError):
    """将 FileNotFoundError 包装为结构化响应"""
    logger.warning("FileNotFoundError: %s", exc)
    message = str(exc)
    if _is_htmx_request(request):
        return _htmx_error_response(message, 404)
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "FILE_NOT_FOUND",
                "message": message,
                "detail": {},
            }
        },
    )


async def _generic_error_handler(request: Request, exc: Exception):
    """兜底处理所有未捕获的异常

    SECURITY (D10): 不向客户端泄露异常类型、堆栈或内部路径，
    仅返回通用错误消息。异常详情通过 logger.exception 记录到服务端日志。
    """
    # 服务端日志：记录完整的异常类型和堆栈，便于排查
    logger.exception("未处理的异常 [%s]: %s", type(exc).__name__, exc)
    # 客户端响应：仅返回通用消息，不泄露任何内部信息
    message = "服务器内部错误，请稍后重试"
    if _is_htmx_request(request):
        return _htmx_error_response(message, 500)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": message,
                # D10: 不再返回 exception_type，防止攻击者指纹识别框架和库版本
                "detail": {},
            }
        },
    )


def register_error_handlers(app) -> None:
    """向 FastAPI 应用注册所有异常处理器

    Args:
        app: FastAPI 应用实例
    """
    # 自定义异常
    app.add_exception_handler(RestoreError, _restore_error_handler)

    # 标准 Python 异常
    app.add_exception_handler(ValueError, _value_error_handler)
    app.add_exception_handler(MemoryError, _memory_error_handler)
    app.add_exception_handler(FileNotFoundError, _file_not_found_error_handler)

    # 兜底
    app.add_exception_handler(Exception, _generic_error_handler)
