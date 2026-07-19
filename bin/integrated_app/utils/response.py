"""统一响应包装工具

REFACTOR: 替代路由层直接使用 JSONResponse({...}) 和 HTTPException 的混合风格，
         所有 API 统一返回 {success, data, error} 结构，便于前端处理与类型推导。
"""
from typing import Any

from fastapi.responses import JSONResponse


def respond_success(data: Any = None, status: int = 200, **extra: Any) -> JSONResponse:
    """成功响应包装

    Args:
        data: 业务数据
        status: HTTP 状态码
        **extra: 顶层附加字段（如 message、task_id 等便于前端读取）

    Returns:
        JSONResponse: {"success": true, "data": ..., **extra}
    """
    body: dict[str, Any] = {"success": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return JSONResponse(status_code=status, content=body)


def respond_error(
    code: str,
    message: str,
    status: int = 400,
    detail: dict[str, Any] | None = None,
) -> JSONResponse:
    """错误响应包装

    Args:
        code: 业务错误码（如 PATH_NOT_ALLOWED、MODEL_NOT_LOADED）
        message: 面向用户的友好错误消息（不应包含敏感信息或用户输入回显）
        status: HTTP 状态码
        detail: 附加详情（不应包含堆栈或技术栈信息）

    Returns:
        JSONResponse: {"success": false, "error": {"code", "message", "detail"}}
    """
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "detail": detail or {},
        },
    }
    return JSONResponse(status_code=status, content=body)
