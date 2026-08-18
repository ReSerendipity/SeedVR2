#!/usr/bin/env python3
"""MCP (Model Context Protocol) 服务器模块（SeedVR2 适配版）。

提供符合 MCP 规范的服务器实现，允许 AI 助手（如 Claude Desktop、Cursor 等）
通过标准化协议调用 SeedVR2 的功能。

请求/响应签名与 TTS_MultiModel/app/integrated_app/mcp_server.py 保持一致：
  - MCPTool / MCPRequest / MCPResponse dataclass
  - MCPServer: register_tool / _handle_request / _handle_initialize /
    _handle_tools_list / _handle_tools_call / _parse_message / run_stdio
  - JSON-RPC 2.0 消息格式，MCP 协议版本 2024-11-05

提供的 MCP 工具 (Tools):
- list_tools: 列出服务器可用工具与可用模型尺寸
- restore: 提交图像/视频修复任务（接现有 engine 推理接口）
- status: 获取模型加载状态与 GPU 显存信息
- history: 查询修复历史记录

支持的传输方式：
- stdio: 标准输入输出（默认，用于 Claude Desktop 等桌面客户端）

设计要点：
- 遵循 MCP 规范（JSON-RPC 2.0 消息格式）
- 延迟导入引擎/数据库等重依赖，避免服务器启动时加载大模型
- 异步实现，支持并发请求
- 提供工具描述、参数 schema 供 LLM 理解
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP 协议常量
# ---------------------------------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "seedvr2"
MCP_SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 数据类（与 TTS_MultiModel 保持一致）
# ---------------------------------------------------------------------------


@dataclass
class MCPTool:
    """MCP 工具定义。

    Attributes:
        name: 工具名称（唯一标识）。
        description: 工具描述（供 LLM 理解用途）。
        input_schema: JSON Schema 定义输入参数。
        handler: 异步处理函数。
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Any


@dataclass
class MCPRequest:
    """MCP JSON-RPC 请求。

    Attributes:
        id: 请求 ID（用于响应匹配）。
        method: 方法名。
        params: 参数字典。
    """

    id: int | str | None
    method: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResponse:
    """MCP JSON-RPC 响应。

    Attributes:
        id: 请求 ID（与请求对应）。
        result: 成功结果。
        error: 错误信息。
    """

    id: int | str | None
    result: Any | None = None
    error: dict[str, Any] | None = None

    def to_json(self) -> str:
        """序列化为 JSON 字符串。

        Returns:
            JSON 字符串。
        """
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            response["error"] = self.error
        else:
            response["result"] = self.result
        return json.dumps(response, ensure_ascii=False)


# ---------------------------------------------------------------------------
# MCP 服务器类
# ---------------------------------------------------------------------------


class MCPServer:
    """MCP 服务器实现。

    处理 JSON-RPC 2.0 消息，提供 tools/list 和 tools/call 等标准方法，
    将 SeedVR2 功能暴露给 AI 助手。

    Usage::

        server = MCPServer()
        await server.run_stdio()
    """

    def __init__(self) -> None:
        """初始化 MCP 服务器，注册所有工具。"""
        self._tools: dict[str, MCPTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """注册默认的 SeedVR2 相关工具。"""
        self.register_tool(
            MCPTool(
                name="list_tools",
                description="列出 SeedVR2 MCP 服务器提供的所有工具，以及可用模型尺寸与精度。",
                input_schema={"type": "object", "properties": {}},
                handler=self._handle_list_tools,
            )
        )

        self.register_tool(
            MCPTool(
                name="restore",
                description=(
                    "提交图像或视频修复（超分辨率/增强）任务。"
                    "输入为本地文件路径（image_path 或 video_path），"
                    "输出修复后的文件路径。支持指定模型尺寸、分辨率、随机种子与精度。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "media_path": {
                            "type": "string",
                            "description": "输入图片或视频的本地绝对路径（按扩展名自动识别类型）",
                        },
                        "model_size": {
                            "type": "string",
                            "description": "模型尺寸：3b / 7b / 7b_sharp，默认 3b",
                            "default": "3b",
                        },
                        "resolution": {
                            "type": "integer",
                            "description": "输出分辨率（短边像素），默认 2160；0 表示用配置默认值",
                            "default": 2160,
                        },
                        "seed": {
                            "type": "integer",
                            "description": "随机种子，-1 表示随机，默认 1373201197",
                            "default": 1373201197,
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "输出目录，默认 outputs/（自动追加 image/ 或 video/ 子目录）",
                        },
                    },
                    "required": ["media_path"],
                },
                handler=self._handle_restore,
            )
        )

        self.register_tool(
            MCPTool(
                name="status",
                description="获取当前模型加载状态（模型尺寸/精度/是否就绪）与 GPU 显存信息。",
                input_schema={"type": "object", "properties": {}},
                handler=self._handle_status,
            )
        )

        self.register_tool(
            MCPTool(
                name="history",
                description="查询修复历史记录（支持按任务类型与状态筛选，分页）。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task_type": {
                            "type": "string",
                            "description": "任务类型筛选：image / video，缺省为全部",
                        },
                        "status": {
                            "type": "string",
                            "description": "状态筛选：pending / processing / completed / failed / cancelled",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回条数上限，默认 20",
                            "default": 20,
                        },
                    },
                },
                handler=self._handle_history,
            )
        )

    def register_tool(self, tool: MCPTool) -> None:
        """注册一个 MCP 工具。

        Args:
            tool: MCPTool 实例。
        """
        self._tools[tool.name] = tool

    async def _handle_request(self, request: MCPRequest) -> MCPResponse:
        """处理单个 MCP 请求。

        Args:
            request: MCP 请求。

        Returns:
            MCP 响应。
        """
        try:
            if request.method == "initialize":
                return self._handle_initialize(request)
            elif request.method == "tools/list":
                return self._handle_tools_list(request)
            elif request.method == "tools/call":
                return await self._handle_tools_call(request)
            elif request.method == "ping":
                return MCPResponse(id=request.id, result={})
            else:
                return MCPResponse(
                    id=request.id,
                    error={
                        "code": -32601,
                        "message": f"方法未找到: {request.method}",
                    },
                )
        except Exception as e:
            logger.error(f"[MCP] 处理请求失败: {e}", exc_info=True)
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"内部错误: {str(e)}",
                },
            )

    def _handle_initialize(self, request: MCPRequest) -> MCPResponse:
        """处理 initialize 方法，返回服务器能力。

        Args:
            request: 初始化请求。

        Returns:
            包含服务器信息和能力的响应。
        """
        return MCPResponse(
            id=request.id,
            result={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {
                    "name": MCP_SERVER_NAME,
                    "version": MCP_SERVER_VERSION,
                },
                "capabilities": {
                    "tools": {"listChanged": False},
                },
            },
        )

    def _handle_tools_list(self, request: MCPRequest) -> MCPResponse:
        """处理 tools/list 方法，返回所有已注册工具。

        Args:
            request: 请求。

        Returns:
            工具列表响应。
        """
        tools_list = []
        for tool in self._tools.values():
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
            )

        return MCPResponse(
            id=request.id,
            result={"tools": tools_list},
        )

    async def _handle_tools_call(self, request: MCPRequest) -> MCPResponse:
        """处理 tools/call 方法，调度到对应工具处理函数。

        Args:
            request: 工具调用请求（包含 name 和 arguments 参数）。

        Returns:
            工具执行结果响应。
        """
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})

        if tool_name not in self._tools:
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32602,
                    "message": f"未知工具: {tool_name}",
                },
            )

        tool = self._tools[tool_name]
        try:
            result = await tool.handler(**arguments)
            return MCPResponse(
                id=request.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, indent=2),
                        }
                    ]
                },
            )
        except TypeError as e:
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32602,
                    "message": f"参数错误: {str(e)}",
                },
            )
        except Exception as e:
            return MCPResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"工具执行失败: {str(e)}",
                },
            )

    # -----------------------------------------------------------------------
    # 工具处理函数
    # -----------------------------------------------------------------------

    async def _handle_list_tools(self, **kwargs: Any) -> dict[str, Any]:
        """列出可用工具与模型尺寸工具处理函数。

        Returns:
            工具列表与可用模型信息。
        """
        try:
            from app.integrated_app.model_registry import model_registry

            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                }
                for tool in self._tools.values()
            ]

            model_info: dict[str, Any] = {"available_sizes": list(model_registry.list_engines())}
            info = model_registry.get_status()
            if info.get("current_model_size"):
                model_info["current_model_size"] = info["current_model_size"]
                model_info["current_precision"] = info.get("current_precision")

            return {"tools": tools, "count": len(tools), "model": model_info}

        except Exception as e:
            logger.error(f"[MCP] 列出工具失败: {e}", exc_info=True)
            return {"tools": [], "count": 0, "error": str(e)}

    async def _handle_restore(
        self,
        media_path: str,
        model_size: str = "3b",
        resolution: int = 2160,
        seed: int = 1373201197,
        output_dir: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """图像/视频修复工具处理函数。

        延迟导入引擎相关模块，通过 model_registry 获取当前引擎实例，
        按扩展名分发到 infer_image / infer_video。

        Args:
            media_path: 输入媒体文件绝对路径。
            model_size: 模型尺寸（3b/7b/7b_sharp）。
            resolution: 输出分辨率。
            seed: 随机种子。
            output_dir: 输出目录（可选，默认 outputs/<image|video>）。

        Returns:
            包含修复结果的字典。
        """
        try:
            import os

            from app.integrated_app.routes.restore.common import detect_media_type

            media_type = detect_media_type(os.path.splitext(media_path)[1])
            if media_type is None:
                return {
                    "success": False,
                    "message": f"不支持的文件格式: {os.path.splitext(media_path)[1]}",
                }

            from app.integrated_app.model_registry import model_registry

            engine = model_registry.get_engine()
            if engine is None:
                return {
                    "success": False,
                    "message": "引擎实例不可用（模型未加载），请先通过 WebUI 或服务加载模型",
                }

            base_dir = output_dir or os.path.join(os.getcwd(), "outputs")
            out_dir = os.path.join(base_dir, media_type)

            if media_type == "image":
                from app.integrated_app.engines.seedvr2_engine import ImageInferenceConfig

                image_config = ImageInferenceConfig(resolution=resolution, seed=seed)
                result = await engine.infer_image(
                    image_path=media_path,
                    output_dir=out_dir,
                    config=image_config,
                )
            else:
                result = await engine.infer_video(
                    video_path=media_path,
                    output_dir=out_dir,
                    resolution=resolution,
                    seed=seed,
                )

            response: dict[str, Any] = {
                "success": result.success,
                "output_path": result.output_path,
                "processing_time": result.processing_time,
                "media_type": media_type,
            }
            if result.error:
                response["message"] = result.error
            if result.metadata:
                response["metadata"] = result.metadata
            return response

        except Exception as e:
            logger.error(f"[MCP] 修复任务失败: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    async def _handle_status(self, **kwargs: Any) -> dict[str, Any]:
        """模型加载状态工具处理函数。

        Returns:
            模型状态与 GPU 显存信息。
        """
        try:
            from app.integrated_app.gpu_backend import gpu_manager
            from app.integrated_app.model_registry import model_registry

            info = model_registry.get_status()
            status: dict[str, Any] = {
                "model_loaded": model_registry.model_loaded,
                "current_model_size": info.get("current_model_size"),
                "current_precision": info.get("current_precision"),
                "model_info": model_registry.model_info or None,
            }

            try:
                gpu_status = gpu_manager.get_status()
                if isinstance(gpu_status, dict):
                    status["gpu"] = {
                        "available": gpu_status.get("available"),
                        "name": gpu_status.get("name"),
                        "vram_total_gb": gpu_status.get("vram_total_gb"),
                        "vram_used_gb": gpu_status.get("vram_used_gb"),
                    }
            except Exception as e:  # noqa: BLE001 — GPU 信息是尽力而为
                status["gpu"] = {"error": str(e)}

            return status

        except Exception as e:
            logger.error(f"[MCP] 获取模型状态失败: {e}", exc_info=True)
            return {"error": str(e)}

    async def _handle_history(
        self,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """历史记录查询工具处理函数。

        Args:
            task_type: 任务类型筛选（image/video）。
            status: 状态筛选。
            limit: 返回条数上限。

        Returns:
            历史记录列表与统计。
        """
        try:
            from app.integrated_app.config import get_app_config
            from app.integrated_app.history_db import HistoryDB

            config = get_app_config()
            db_path = config.get("history", {}).get("db_path", "data/history.db")

            limit = max(1, min(int(limit), 100))
            records: list[dict[str, Any]] = []
            total = 0

            async with HistoryDB(db_path=db_path) as db:
                await db.initialize()
                rows, total = await db.get_records(
                    task_type=task_type,
                    status=status,
                    limit=limit,
                    offset=0,
                )
                for r in rows:
                    records.append(
                        {
                            "id": r.id,
                            "task_type": r.task_type,
                            "input_file": r.input_file,
                            "output_file": r.output_file,
                            "status": r.status,
                            "model_size": r.model_size,
                            "error_message": r.error_message,
                            "created_at": r.created_at,
                        }
                    )

            return {
                "records": records,
                "total": total,
                "limit": limit,
            }

        except Exception as e:
            logger.error(f"[MCP] 查询历史失败: {e}", exc_info=True)
            return {"records": [], "total": 0, "error": str(e)}

    # -----------------------------------------------------------------------
    # 传输层
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_message(line: str) -> MCPRequest | None:
        """解析一行 JSON-RPC 消息。

        Args:
            line: JSON 字符串行。

        Returns:
            MCPRequest 实例，解析失败返回 None。
        """
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
            return MCPRequest(
                id=data.get("id"),
                method=data.get("method", ""),
                params=data.get("params", {}),
            )
        except json.JSONDecodeError as e:
            logger.warning(f"[MCP] JSON 解析失败: {e}, line: {line[:100]}")
            return None

    async def run_stdio(self) -> None:
        """通过 stdio 运行 MCP 服务器。

        从 stdin 读取 JSON-RPC 请求，处理后将响应写入 stdout。
        这是 Claude Desktop 等桌面客户端的标准接入方式。
        """
        logger.info("[MCP] MCP 服务器启动 (stdio 模式)")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace")
                request = self._parse_message(line_str)

                if request is None:
                    continue

                response = await self._handle_request(request)
                response_json = response.to_json()

                sys.stdout.write(response_json + "\n")
                sys.stdout.flush()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MCP] 主循环错误: {e}", exc_info=True)

        logger.info("[MCP] MCP 服务器停止")


# ---------------------------------------------------------------------------
# 便捷启动函数
# ---------------------------------------------------------------------------


def run_mcp_server(transport: str = "stdio") -> None:
    """启动 MCP 服务器。

    Args:
        transport: 传输方式，目前支持 "stdio"。
    """
    server = MCPServer()

    if transport == "stdio":
        asyncio.run(server.run_stdio())
    else:
        raise ValueError(f"不支持的传输方式: {transport}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_mcp_server()
