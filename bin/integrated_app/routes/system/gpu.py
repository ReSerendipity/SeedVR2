#!/usr/bin/env python3
"""SeedVR2 工具箱 - GPU 信息路由"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bin.integrated_app.dependencies import get_gpu_backend
from bin.integrated_app.gpu_backend import GPUBackendManager
from bin.integrated_app.gpu_utils import get_full_system_info, get_gpu_memory_info

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/gpu")
async def gpu_info(gpu_backend: GPUBackendManager = Depends(get_gpu_backend)):
    """获取 GPU 信息"""
    info = gpu_backend.get_gpu_info()
    memory_info = get_gpu_memory_info()

    # 获取 CUDA 版本
    cuda_version = ""
    try:
        import torch
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda or ""
    except Exception:
        pass

    return JSONResponse({
        "backend": info.backend.value,
        "device_name": info.name,
        "vram_total_mb": info.total_vram_mb,
        "vram_available_mb": info.available_vram_mb,
        "utilization_pct": round(info.utilization_pct, 2),
        "cuda_version": cuda_version,
        "driver_version": info.driver_version,
        "memory": memory_info,
    })


@router.get("/gpu/system")
async def system_info():
    """获取完整系统信息"""
    return JSONResponse(get_full_system_info())
