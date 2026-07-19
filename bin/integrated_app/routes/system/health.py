#!/usr/bin/env python3
"""SeedVR2 工具箱 - 系统健康检查路由（仅支持 NVIDIA CUDA GPU）"""
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

# 服务启动时间
_start_time = time.time()


@router.get("/ping")
async def api_health_check(
    request: Request,
    gpu_backend: GPUBackendManager = Depends(get_gpu_backend),
):
    """轻量级存活探针，供负载均衡器或监控使用

    REFACTOR: 原路径 /api/health 在 /api/system 前缀下会变成 /api/system/api/health
    （双 api 前缀 bug），改为 /ping 后实际路径为 /api/system/ping。
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
    """系统健康检查（详细版）"""
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
