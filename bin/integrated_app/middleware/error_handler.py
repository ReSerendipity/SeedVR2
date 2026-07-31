"""FastAPI 全局异常处理器。

为所有自定义异常和标准 Python 异常注册 FastAPI exception handler，
返回统一结构的 JSON 响应，并区分普通 API 请求与 HTMX 增强请求。

响应策略:
    - 普通 API 请求：返回统一 JSON 结构 {error: {code, message, detail}}
    - HTMX 请求：返回 HX-Trigger 头触发前端 Toast 提示，无响应体

安全策略:
    - 兜底异常处理器不向客户端泄露异常类型、堆栈或内部路径
    - 仅返回通用错误消息，异常详情通过 logger.exception 记录到服务端日志
    - 防止攻击者通过错误信息指纹识别框架和库版本

设计模式:
    - 责任链模式：按异常类型匹配对应的处理器，未匹配则走兜底
    - 策略模式：根据请求类型（普通/HTMX）选择不同的响应格式
"""

import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from bin.integrated_app.exceptions import RestoreError

logger = logging.getLogger(__name__)


def _build_error_body(exc: RestoreError) -> dict:
    """构建 RestoreError 的统一错误响应体。

    Args:
        exc: RestoreError 异常实例，包含 code、message、detail 属性

    Returns:
        dict: 结构化错误体 {error: {code, message, detail}}
    """
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        }
    }


def _is_htmx_request(request: Request) -> bool:
    """判断请求是否来自 HTMX 增强的前端。

    HTMX 请求会携带 HX-Request: true 头。

    Args:
        request: FastAPI 请求对象

    Returns:
        bool: HTMX 请求返回 True
    """
    return request.headers.get("HX-Request") == "true"


def _htmx_error_response(message: str, status: int = 400) -> Response:
    """为 HTMX 请求返回带 HX-Trigger 的错误响应，触发前端 Toast 提示。

    HTMX 会自动解析 HX-Trigger 头中的 JSON 并触发对应的客户端事件。

    Args:
        message: 错误提示消息
        status: HTTP 状态码，默认 400

    Returns:
        Response: 空响应体，通过 HX-Trigger 头传递错误信息
    """
    return Response(
        status_code=status,
        headers={
            "HX-Trigger": json.dumps(
                {"showToast": {"message": message, "type": "error"}},
                ensure_ascii=False,
            )
        },
    )


async def _restore_error_handler(request: Request, exc: RestoreError) -> Response:
    """处理所有 RestoreError 子类异常。

    RestoreError 是应用自定义业务异常基类，包含错误码和 HTTP 状态码映射。

    Args:
        request: FastAPI 请求对象
        exc: RestoreError 异常实例

    Returns:
        Response: 结构化错误响应
    """
    status = exc.http_status()
    logger.warning("RestoreError [%s] %s — %s", exc.code, exc.message, exc.detail)
    if _is_htmx_request(request):
        return _htmx_error_response(exc.message, status)
    return JSONResponse(status_code=status, content=_build_error_body(exc))


async def _value_error_handler(request: Request, exc: ValueError) -> Response:
    """将 ValueError 包装为结构化响应。

    通常用于参数验证失败、配置错误等场景，返回 422 状态码。

    Args:
        request: FastAPI 请求对象
        exc: ValueError 异常实例

    Returns:
        Response: 结构化错误响应
    """
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


async def _memory_error_handler(request: Request, exc: MemoryError) -> Response:
    """将 MemoryError 包装为结构化响应。

    内存不足时返回友好提示，建议用户降低分辨率或缩小输入尺寸。

    Args:
        request: FastAPI 请求对象
        exc: MemoryError 异常实例

    Returns:
        Response: 结构化错误响应
    """
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


async def _file_not_found_error_handler(request: Request, exc: FileNotFoundError) -> Response:
    """将 FileNotFoundError 包装为结构化响应。

    文件不存在时返回 404 状态码。

    Args:
        request: FastAPI 请求对象
        exc: FileNotFoundError 异常实例

    Returns:
        Response: 结构化错误响应
    """
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


async def _generic_error_handler(request: Request, exc: Exception) -> Response:
    """兜底处理所有未捕获的异常。

    安全策略 (D10):
        - 不向客户端泄露异常类型、堆栈或内部路径
        - 仅返回通用错误消息"服务器内部错误，请稍后重试"
        - 异常详情通过 logger.exception 记录完整堆栈到服务端日志
        - 不再返回 exception_type 字段，防止攻击者指纹识别框架和库版本

    Args:
        request: FastAPI 请求对象
        exc: 未被前面处理器捕获的任意异常

    Returns:
        Response: 通用 500 错误响应
    """
    logger.exception("未处理的异常 [%s]: %s", type(exc).__name__, exc)
    message = "服务器内部错误，请稍后重试"
    if _is_htmx_request(request):
        return _htmx_error_response(message, 500)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": message,
                "detail": {},
            }
        },
    )


def register_error_handlers(app) -> None:
    """向 FastAPI 应用注册所有异常处理器。

    注册顺序：先注册具体异常类型，最后注册兜底 Exception。
    FastAPI 按注册顺序匹配，具体类型优先于通用类型。

    Args:
        app: FastAPI 应用实例
    """
    app.add_exception_handler(RestoreError, _restore_error_handler)

    app.add_exception_handler(ValueError, _value_error_handler)
    app.add_exception_handler(MemoryError, _memory_error_handler)
    app.add_exception_handler(FileNotFoundError, _file_not_found_error_handler)

    app.add_exception_handler(Exception, _generic_error_handler)
