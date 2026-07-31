#!/usr/bin/env python3
"""系统健康检查路由模块。

提供系统存活探针和详细健康检查端点，用于负载均衡、监控和服务状态查询。

API 端点：
- GET /api/system/ping: 轻量级存活探针
- GET /api/system/health: 详细系统健康检查（含系统资源、模型、GPU 信息）

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
注意：SeedVR2 仅支持 NVIDIA CUDA GPU。
"""
import logging
import platform
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bin.integrated_app.dependencies import get_gpu_backend, get_model_manager
from bin.integrated_app.gpu_backend import GPUBackendManager
from bin.integrated_app.model_manager import ModelManager

logger = logging.getLogger(__name__)
router = APIRouter()

_start_time = time.time()


@router.get("/ping")
async def api_health_check(
    request: Request,
    gpu_backend: GPUBackendManager = Depends(get_gpu_backend),
):
    """轻量级存活探针端点。

    API 端点：GET /api/system/ping

    供负载均衡器或监控系统快速检测服务是否存活。响应体小、处理快，
    不做复杂的资源检查。

    请求参数：无

    返回格式（JSON）：
    {
        "status": "ok",
        "version": str,
        "gpu_available": bool
    }

    Args:
        request: FastAPI 请求对象。
        gpu_backend: GPU 后端管理器实例（通过依赖注入）。

    Returns:
        JSON 响应，包含存活状态、版本号和 GPU 可用性。
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "gpu_available": gpu_backend.is_gpu_available,
    }


@router.get("/health")
async def health_check(
    model_manager: ModelManager = Depends(get_model_manager),
    gpu_backend: GPUBackendManager = Depends(get_gpu_backend),
):
    """详细系统健康检查端点。

    API 端点：GET /api/system/health

    返回系统运行状态的详细信息，包括：
    - 服务状态与运行时长
    - 系统信息（平台、Python 版本、CPU、内存）
    - 模型加载状态
    - GPU 信息（后端、设备名、可用性）

    请求参数：无

    返回格式（JSON）：
    {
        "status": "ok",
        "uptime_seconds": float,
        "system": {
            "platform": str,
            "python_version": str,
            "cpu_count": int,
            "memory_total_gb": float,
            "memory_available_gb": float,
            "memory_utilization_pct": float
        },
        "model": { ... },      // 模型状态详情
        "gpu": {
            "backend": str,
            "device_name": str,
            "is_gpu_available": bool
        }
    }

    注意：如 psutil 未安装，系统资源字段返回 0。

    Args:
        model_manager: 模型管理器实例（通过依赖注入）。
        gpu_backend: GPU 后端管理器实例（通过依赖注入）。

    Returns:
        JSONResponse 包含详细健康信息。
    """
    try:
        import psutil
        cpu_count = psutil.cpu_count()
        mem = psutil.virtual_memory()
        memory_total_gb = round(mem.total / (1024 ** 3), 2)
        memory_available_gb = round(mem.available / (1024 ** 3), 2)
        memory_pct = mem.percent
    except ImportError:
        cpu_count = 0
        memory_total_gb = 0
        memory_available_gb = 0
        memory_pct = 0

    uptime = round(time.time() - _start_time, 1)

    return JSONResponse({
        "status": "ok",
        "uptime_seconds": uptime,
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": cpu_count,
            "memory_total_gb": memory_total_gb,
            "memory_available_gb": memory_available_gb,
            "memory_utilization_pct": memory_pct,
        },
        "model": model_manager.get_status(),
        "gpu": {
            "backend": gpu_backend.backend.value,
            "device_name": gpu_backend.device_name,
            "is_gpu_available": gpu_backend.is_gpu_available,
        },
    })
