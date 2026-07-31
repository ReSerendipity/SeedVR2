#!/usr/bin/env python3
"""GPU 信息查询路由模块。

提供 GPU 硬件信息和完整系统信息查询端点，用于前端展示和诊断。

API 端点：
- GET /api/system/gpu: 获取 GPU 详细信息（显存、利用率、CUDA 版本等）
- GET /api/system/gpu/system: 获取完整系统信息

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
注意：仅支持 NVIDIA CUDA GPU。
"""
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
    """获取 GPU 详细信息端点。

    API 端点：GET /api/system/gpu

    返回 GPU 硬件信息，包括：
    - 后端类型、设备名称
    - 显存总量/可用量（MB）
    - GPU 利用率
    - CUDA 版本、驱动版本
    - 详细显存信息

    请求参数：无

    返回格式（JSON）：
    {
        "backend": str,           // 如 "cuda"
        "device_name": str,       // GPU 设备名称
        "vram_total_mb": int,
        "vram_available_mb": int,
        "utilization_pct": float,
        "cuda_version": str,
        "driver_version": str,
        "memory": { ... }         // 详细显存信息
    }

    Args:
        gpu_backend: GPU 后端管理器实例（通过依赖注入）。

    Returns:
        JSONResponse 包含 GPU 信息。
    """
    info = gpu_backend.get_gpu_info()
    memory_info = get_gpu_memory_info()

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
    """获取完整系统信息端点。

    API 端点：GET /api/system/gpu/system

    返回包含 CPU、内存、GPU、CUDA、PyTorch 等完整系统信息，
    用于问题诊断和环境确认。

    请求参数：无

    返回格式（JSON）：由 get_full_system_info() 返回的系统信息字典。

    Returns:
        JSONResponse 包含完整系统信息。
    """
    return JSONResponse(get_full_system_info())
