"""mcp_server.py 冒烟测试。

验证 MCP 服务器实例化、工具注册、JSON-RPC 请求/响应签名一致性。
不依赖 GPU 或引擎实例 —— 纯结构/签名测试。
"""

from __future__ import annotations

import json
import logging

import pytest

from app.integrated_app.mcp_server import (
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCPRequest,
    MCPResponse,
    MCPServer,
)

# 抑制测试中的日志噪音
logging.getLogger("app.integrated_app.mcp_server").setLevel(logging.CRITICAL)


class TestMCPDataclasses:
    """MCPRequest/MCPResponse 签名一致性。"""

    def test_request_fields(self):
        req = MCPRequest(id=1, method="tools/list", params={"name": "test"})
        assert req.id == 1
        assert req.method == "tools/list"
        assert req.params == {"name": "test"}

    def test_request_default_params(self):
        req = MCPRequest(id=None, method="ping")
        assert req.params == {}

    def test_response_success(self):
        resp = MCPResponse(id=1, result={"tools": []})
        js = resp.to_json()
        data = json.loads(js)
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert data["result"] == {"tools": []}

    def test_response_error(self):
        resp = MCPResponse(id=1, error={"code": -32601, "message": "Not found"})
        js = resp.to_json()
        data = json.loads(js)
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert data["error"]["code"] == -32601

    def test_to_json_no_error_key_in_success(self):
        resp = MCPResponse(id=2, result={"ok": True})
        js = resp.to_json()
        assert "error" not in json.loads(js)


class TestMCPServerInstantiation:
    """MCPServer 实例化与工具注册。"""

    def setup_method(self):
        self.server = MCPServer()

    def test_server_has_4_tools(self):
        """需注册 list_tools / restore / status / history 四个工具。"""
        assert len(self.server._tools) == 4
        assert set(self.server._tools.keys()) == {
            "list_tools",
            "restore",
            "status",
            "history",
        }

    def test_tools_have_required_fields(self):
        """每个工具必须有 name / description / inputSchema。"""
        for tool in self.server._tools.values():
            assert isinstance(tool.name, str) and len(tool.name) > 0
            assert isinstance(tool.description, str) and len(tool.description) > 0
            assert isinstance(tool.input_schema, dict)

    def test_tools_list_method_returns_correct_structure(self):
        """tools/list 返回的 tool 结构：name / description / inputSchema。"""
        request = MCPRequest(id=1, method="tools/list")
        response = self.server._handle_tools_list(request)
        assert response.id == 1
        tools = response.result["tools"]
        assert len(tools) == 4
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t

    def test_initialize_returns_correct_info(self):
        """initialize 返回 protocolVersion / serverInfo.name.version / capabilities。"""
        request = MCPRequest(id=1, method="initialize")
        response = self.server._handle_initialize(request)
        result = response.result
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == MCP_SERVER_NAME
        assert result["serverInfo"]["version"] == MCP_SERVER_VERSION
        assert "tools" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_ping_returns_empty_result(self):
        request = MCPRequest(id=1, method="ping")
        response = await self.server._handle_request(request)
        assert response.id == 1
        assert response.result == {}
        assert response.error is None

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self):
        request = MCPRequest(id=1, method="nonexistent")
        response = await self.server._handle_request(request)
        assert response.error is not None
        assert response.error["code"] == -32601

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """tools/call 未知工具名返回 -32602。"""
        request = MCPRequest(id=2, method="tools/call", params={"name": "unknown_tool"})
        response = await self.server._handle_tools_call(request)
        assert response.error is not None
        assert response.error["code"] == -32602

    @pytest.mark.asyncio
    async def test_handle_request_routes_to_tools_list(self):
        """_handle_request 对 tools/list 方法正确路由。"""
        request = MCPRequest(id=1, method="tools/list")
        response = await self.server._handle_request(request)
        assert response.result is not None
        assert len(response.result["tools"]) == 4

    @pytest.mark.asyncio
    async def test_handle_request_routes_to_initialize(self):
        request = MCPRequest(id=1, method="initialize")
        response = await self.server._handle_request(request)
        assert response.result["protocolVersion"] == MCP_PROTOCOL_VERSION

    def test_parse_message_valid_json(self):
        msg = '{"jsonrpc":"2.0","id":42,"method":"tools/list","params":{}}'
        req = MCPServer._parse_message(msg)
        assert req is not None
        assert req.id == 42
        assert req.method == "tools/list"

    def test_parse_message_invalid_json(self):
        req = MCPServer._parse_message("{invalid")
        assert req is None

    def test_parse_message_empty_line(self):
        assert MCPServer._parse_message("") is None
        assert MCPServer._parse_message("   ") is None

    @pytest.mark.asyncio
    async def test_handle_request_unknown_method_error(self):
        request = MCPRequest(id=1, method="unknown_method")
        response = await self.server._handle_request(request)
        assert response.error is not None
        assert response.error["code"] == -32601


if __name__ == "__main__":
    pytest.main([__file__, "-q", "-p", "no:cacheprovider"])
