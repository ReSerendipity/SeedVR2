#!/usr/bin/env python3
"""性能指标监控路由模块。

提供运行时性能 KPI 指标查询端点，用于系统监控和运维。

API 端点：
- GET /api/system/metrics: 获取当前性能指标快照
- GET /api/system/metrics/inference: 获取推理历史记录

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import logging

from fastapi import APIRouter

from bin.integrated_app.metrics import metrics_collector
from bin.integrated_app.utils.response import respond_success

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/metrics")
async def get_metrics():
    """获取当前性能指标快照

    返回系统运行时间、内存使用率、GPU 显存/利用率、
    推理次数/成功率/平均耗时、缓存统计等 KPI 指标。

    Returns:
        JSON 响应，data 字段包含指标快照字典
    """
    snapshot = metrics_collector.snapshot()
    return respond_success(data=snapshot.to_dict())


@router.get("/metrics/inference")
async def get_inference_history():
    """获取最近的推理历史记录

    返回最近 100 条推理记录，包含时间戳、耗时、成功/失败、模型大小等。

    Returns:
        JSON 响应，data 字段包含推理记录列表
    """
    with metrics_collector._lock:
        records = [
            {
                "timestamp": r.timestamp,
                "duration": round(r.duration, 2),
                "success": r.success,
                "model_size": r.model_size,
                "input_type": r.input_type,
            }
            for r in metrics_collector._inference_records
        ]
    return respond_success(data=records)


@router.post("/metrics/reset")
async def reset_metrics():
    """重置推理计数器

    清空推理历史记录和计数器，不重置运行时间。
    用于运维场景下的指标重置。

    Returns:
        JSON 响应，确认重置成功
    """
    metrics_collector.reset()
    return respond_success(data={"status": "ok"})
