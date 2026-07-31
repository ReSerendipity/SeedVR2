"""统一响应包装工具。

替代路由层直接使用 JSONResponse({...}) 和 HTTPException 的混合风格，
所有 API 统一返回 {success, data, error} 结构，便于前端处理与类型推导。

设计模式:
    - 工厂模式：提供 respond_success / respond_error 两个工厂函数
    - 约定优于配置：统一响应结构，减少前端判断分支
    - 不可变输出：函数返回全新的 dict，避免调用方意外修改共享对象

响应结构约定:
    成功: {"success": true, "data": <业务数据>, ...<额外字段>}
    失败: {"success": false, "error": {"code": <错误码>, "message": <消息>, "detail": <详情>}}
"""
from typing import Any

from fastapi.responses import JSONResponse


def respond_success(data: Any = None, status: int = 200, **extra: Any) -> JSONResponse:
    """成功响应包装工厂函数。

    构建统一格式的成功 JSON 响应，可选附加顶层字段便于前端快速读取
    （如 task_id、message 等无需嵌套在 data 中的信息）。

    Args:
        data: 业务数据主体，为 None 时不包含 data 字段
        status: HTTP 状态码，默认 200 OK
        **extra: 顶层附加字段，会合并到响应根级别

    Returns:
        JSONResponse: FastAPI JSON 响应对象
            格式为 {"success": true, "data": ..., **extra}
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
    """错误响应包装工厂函数。

    构建统一格式的错误 JSON 响应，所有业务错误通过此函数返回，
    确保前端能一致地解析错误码和错误消息。

    安全提示:
        - message 应面向用户，不包含敏感信息（如路径、SQL、堆栈）
        - detail 仅用于调试补充信息，生产环境不应包含技术栈细节

    Args:
        code: 业务错误码字符串（如 PATH_NOT_ALLOWED、MODEL_NOT_LOADED、INSUFFICIENT_RAM）
        message: 面向用户的友好错误消息，应清晰说明问题并给出建议
        status: HTTP 状态码，默认 400 Bad Request
        detail: 附加详情字典，默认为空字典；不应包含堆栈或敏感信息

    Returns:
        JSONResponse: FastAPI JSON 响应对象
            格式为 {"success": false, "error": {"code", "message", "detail"}}
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
