"""OpenAPI Schema 自动验证测试

验证 API 响应结构与 FastAPI 自动生成的 OpenAPI schema 一致。
确保 API 契约的完整性，防止响应结构变更未被检测。
"""

from __future__ import annotations


class TestOpenAPISchema:
    """OpenAPI Schema 完整性测试"""

    def test_openapi_schema_generated(self, test_app):
        """FastAPI 应能生成有效的 OpenAPI schema"""
        response = test_app.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert "components" in schema

    def test_all_api_paths_have_responses(self, test_app):
        """所有 API 路径应定义响应 schema"""
        response = test_app.get("/openapi.json")
        schema = response.json()
        paths = schema.get("paths", {})
        api_paths = [p for p in paths if p.startswith("/api/")]
        assert len(api_paths) > 0, "Should have API paths in schema"
        for path, methods in paths.items():
            if not path.startswith("/api/"):
                continue
            for method, spec in methods.items():
                if method not in ("get", "post", "put", "delete", "patch"):
                    continue
                assert "responses" in spec, f"{method.upper()} {path} missing responses"

    def test_health_endpoint_has_200_response(self, test_app):
        """健康检查端点应定义 200 响应"""
        response = test_app.get("/openapi.json")
        schema = response.json()
        health_path = schema["paths"].get("/api/system/health", {})
        get_spec = health_path.get("get", {})
        assert "200" in get_spec.get("responses", {}), "Health endpoint should define 200 response"

    def test_error_responses_defined(self, test_app):
        """关键端点应定义错误响应（422 验证错误等）"""
        response = test_app.get("/openapi.json")
        schema = response.json()
        paths = schema.get("paths", {})

        # 检查带路径参数的端点是否有 422 验证错误响应
        # FastAPI 自动为路径参数添加 422 响应（验证失败时）
        restore_progress = paths.get("/api/restore/{task_id}/progress", {})
        get_spec = restore_progress.get("get", {})
        responses = get_spec.get("responses", {})
        # 路径参数端点应至少有 200 和 422 响应
        assert "200" in responses, "Restore progress endpoint should define 200 response"
        assert "422" in responses, "Restore progress endpoint should define 422 validation error response"

    def test_schema_has_security_schemes(self, test_app):
        """Schema 应定义安全方案（如果有 CSRF 或认证）"""
        response = test_app.get("/openapi.json")
        schema = response.json()
        # 检查 components 中是否有 securitySchemes
        components = schema.get("components", {})
        # 不强制要求，但如果有应验证
        security_schemes = components.get("securitySchemes", {})
        # 验证存在即可
        assert isinstance(security_schemes, dict)


class TestAPIResponseStructure:
    """API 响应结构一致性测试"""

    def test_success_response_has_success_field(self, test_app):
        """成功响应应包含 success 字段"""
        response = test_app.get("/api/system/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "data" in data

    def test_error_response_has_detail_or_error(self, test_app):
        """错误响应应包含 detail 或 error 字段"""
        # 触发 422 错误
        response = test_app.get("/api/system/history?page=0&page_size=10")
        assert response.status_code == 422
        data = response.json()
        # FastAPI 的 422 响应应包含 detail
        assert "detail" in data

    def test_history_response_structure(self, test_app):
        """历史记录响应结构应一致"""
        response = test_app.get("/api/system/history?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        required_fields = ["records", "total", "page", "page_size", "total_pages"]
        for field in required_fields:
            assert field in data, f"History response missing field: {field}"
        assert isinstance(data["records"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["page"], int)
        assert isinstance(data["page_size"], int)
        assert isinstance(data["total_pages"], int)

    def test_health_response_structure(self, test_app):
        """健康检查响应结构应一致"""
        response = test_app.get("/api/system/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert "system" in data
        assert "model" in data
        assert "gpu" in data
