"""SeedVR2 测试配置"""
import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bin.integrated_app.app_server import create_app  # noqa: E402
from bin.integrated_app.config import load_config  # noqa: E402

if TYPE_CHECKING:
    from starlette.responses import Response


def get_csrf_token(client: TestClient) -> str | None:
    """从 TestClient 获取 CSRF token

    通过一次 GET 请求触发 CSRFMiddleware 设置 cookie，
    后续 POST 请求需将此 token 同时作为 cookie 和 X-CSRF-Token header 传递。

    Args:
        client: TestClient 实例

    Returns:
        CSRF token 字符串，或 None（如果 cookie 未设置）
    """
    client.get("/")
    return client.cookies.get("csrf_token")


def csrf_post(client: TestClient, url: str, **kwargs) -> "Response":
    """带 CSRF token 的 POST 请求 helper

    自动获取 CSRF token 并添加 X-CSRF-Token header，
    简化需要 CSRF 保护的路由测试。

    Args:
        client: TestClient 实例
        url: 请求 URL
        **kwargs: 传递给 client.post 的额外参数（data, json, files 等）

    Returns:
        POST 响应
    """
    token = get_csrf_token(client)
    headers = kwargs.pop("headers", {})
    if token:
        headers["X-CSRF-Token"] = token
    return client.post(url, headers=headers, **kwargs)


@pytest.fixture
def test_app(tmp_path):
    """创建用于测试的 FastAPI 应用与 TestClient

    - 使用临时数据库路径，避免污染生产数据
    - 关闭模型自动加载，避免真实推理依赖
    - Mock model_manager 的重依赖方法
    """
    config = load_config()
    config.setdefault("history", {})["db_path"] = str(tmp_path / "history.db")
    config.setdefault("model", {})["auto_load"] = False
    config.setdefault("server", {})["auto_open_browser"] = False

    app = create_app(config)

    # Mock 重依赖，避免测试触发真实模型加载/卸载
    mock_manager = AsyncMock()
    mock_manager.unload_model = AsyncMock(return_value={"status": "ok"})
    mock_manager.load_model = AsyncMock(return_value={"status": "ok"})
    app.state.model_manager = mock_manager

    with TestClient(app) as client:
        yield client
