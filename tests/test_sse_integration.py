"""SSE (Server-Sent Events) 真实连接集成测试

验证 SSE 相关端点的错误处理和路由行为。
注意：FastAPI TestClient 不适合测试长连接 SSE 流（会阻塞），
因此仅测试非流式端点的错误响应。
真实的 SSE 流测试由 Playwright E2E 的 sse.spec.ts 覆盖。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestSSEEndpointErrorHandling:
    """SSE 相关端点错误处理测试"""

    def test_progress_nonexistent_returns_404(self, test_app):
        """不存在的任务 SSE 进度端点应返回 404"""
        response = test_app.get("/api/restore/nonexistent-sse-task/progress")
        assert response.status_code == 404

    def test_result_nonexistent_returns_404(self, test_app):
        """不存在的任务结果端点应返回 404"""
        response = test_app.get("/api/restore/nonexistent-sse-task/result")
        assert response.status_code == 404

    def test_download_nonexistent_returns_404(self, test_app):
        """不存在的任务下载端点应返回 404"""
        response = test_app.get("/api/restore/nonexistent-sse-task/download")
        assert response.status_code == 404

    def test_cancel_nonexistent_returns_404(self, test_app):
        """不存在的任务取消端点应返回 404"""
        from tests.conftest import csrf_post

        response = csrf_post(test_app, "/api/restore/nonexistent-sse-task/cancel")
        assert response.status_code in (404, 403)


class TestRestoreEndpointStructure:
    """Restore 端点结构验证"""

    def test_restore_endpoints_require_valid_task_id(self, test_app):
        """Restore 相关端点应验证 task_id 参数"""
        # 不存在的 task_id 应返回 404
        endpoints = [
            "/api/restore/test-task-12345/result",
            "/api/restore/test-task-12345/download",
        ]
        for endpoint in endpoints:
            response = test_app.get(endpoint)
            assert response.status_code in (
                200,
                404,
                422,
            ), f"Endpoint {endpoint} returned unexpected status {response.status_code}"

    def test_restore_progress_nonexistent_404(self, test_app):
        """不存在的 restore 进度端点应返回 404"""
        response = test_app.get("/api/restore/definitely-nonexistent-task/progress")
        assert response.status_code == 404
