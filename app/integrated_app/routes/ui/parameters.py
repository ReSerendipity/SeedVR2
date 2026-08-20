#!/usr/bin/env python3
"""UI 参数面板与用户偏好 API 路由模块。

暴露 webui_enhancement 模块的后端框架组件，为前端提供：
- 参数定义与预设组合查询
- 基于当前参数值的智能推荐
- 参数合法性校验
- 用户偏好设置的持久化（加载/保存/重置）
- 折叠面板布局分组信息

API 端点：
- GET /api/ui/parameters: 获取所有参数定义和预设组合
- GET /api/ui/parameters/recommendations: 根据当前参数获取推荐预设
- POST /api/ui/parameters/validate: 验证参数值合法性
- GET /api/ui/preferences: 加载用户偏好
- POST /api/ui/preferences: 保存用户偏好
- POST /api/ui/preferences/reset: 重置用户偏好为默认值
- GET /api/ui/layout: 获取折叠面板布局分组

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui", tags=["UI参数与偏好"])


def _get_optimizer():
    """获取参数面板优化器实例（内部懒加载函数）。

    延迟导入 create_default_parameter_panel，避免循环依赖和启动时不必要的加载。

    Returns:
        参数面板优化器实例。
    """
    from app.integrated_app.optimization.webui_enhancement import create_default_parameter_panel

    return create_default_parameter_panel()


def _get_persistence():
    """获取设置持久化管理器实例（内部懒加载函数）。

    Returns:
        SettingsPersistence 实例。
    """
    from app.integrated_app.optimization.webui_enhancement import SettingsPersistence

    return SettingsPersistence()


def _get_layout_manager():
    """获取折叠面板布局管理器实例（内部懒加载函数）。

    Returns:
        AccordionLayoutManager 实例。
    """
    from app.integrated_app.optimization.webui_enhancement import AccordionLayoutManager

    return AccordionLayoutManager()


@router.get("/parameters")
async def get_parameters():
    """获取所有参数定义和预设组合。

    API 端点：GET /api/ui/parameters

    请求参数：无

    返回格式（JSON，统一包装 {success, data}）：
    {
        "success": true,
        "data": {
            "parameters": [
                {
                    "id": str,
                    "name": str,
                    "type": str,
                    "default": any,
                    "min": number?,
                    "max": number?,
                    "step": number?,
                    "choices": list?,
                    "description": str,
                    "group": str,
                    "advanced": bool
                }
            ],
            "presets": [
                {
                    "name": str,
                    "description": str,
                    "values": dict,
                    "recommended_ranges": dict,
                    "use_case": str
                }
            ]
        }
    }

    Returns:
        包含参数定义和预设列表的字典。
    """
    optimizer = _get_optimizer()

    params = []
    for p in optimizer.get_all_params():
        params.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.param_type,
                "default": p.default,
                "min": p.min_value,
                "max": p.max_value,
                "step": p.step,
                "choices": p.choices,
                "description": p.description,
                "group": p.group,
                "advanced": p.advanced,
            }
        )

    presets = []
    for preset in optimizer.get_presets():
        presets.append(
            {
                "name": preset.name,
                "description": preset.description,
                "values": preset.preset_values,
                "recommended_ranges": {k: {"min": v[0], "max": v[1]} for k, v in preset.recommended_ranges.items()},
                "use_case": preset.use_case,
            }
        )

    return {"success": True, "data": {"parameters": params, "presets": presets}}


@router.get("/parameters/recommendations")
async def get_recommendations(cfg_scale: float = 3.0, denoising_strength: float = 0.6, steps: int = 20):
    """根据当前参数值获取推荐预设，按匹配度排序。

    API 端点：GET /api/ui/parameters/recommendations

    查询参数：
    - cfg_scale (optional): CFG Scale，默认 3.0
    - denoising_strength (optional): 去噪强度，默认 0.6
    - steps (optional): 采样步数，默认 20

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "recommendations": [
                {
                    "name": str,
                    "description": str,
                    "values": dict,
                    "match_score": float,
                    "use_case": str
                }
            ]
        }
    }

    Args:
        cfg_scale: CFG 引导系数。
        denoising_strength: 去噪强度。
        steps: 推理步数。

    Returns:
        按匹配度排序的推荐预设列表。
    """
    optimizer = _get_optimizer()
    recommendations = optimizer.get_recommendations(
        cfg_scale=cfg_scale,
        denoising_strength=denoising_strength,
        steps=steps,
    )

    result = []
    for rec in recommendations:
        preset = rec["preset"]
        result.append(
            {
                "name": preset.name,
                "description": preset.description,
                "values": preset.preset_values,
                "match_score": rec["match_score"],
                "use_case": rec["use_case"],
            }
        )

    return {"success": True, "data": {"recommendations": result}}


@router.post("/parameters/validate")
async def validate_parameters(values: dict):
    """验证参数值是否在合法范围内。

    API 端点：POST /api/ui/parameters/validate

    请求体（JSON）：参数字典，如 {"cfg_scale": 3.0, "denoising_strength": 0.6, ...}

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "errors": dict,    // 字段名 -> 错误信息，空字典表示全部合法
            "valid": bool      // 是否全部合法
        }
    }

    Args:
        values: 待验证的参数字典。

    Returns:
        验证结果，包含错误字典和 valid 标志。
    """
    optimizer = _get_optimizer()
    errors = optimizer.validate_values(values)
    return {"success": True, "data": {"errors": errors, "valid": len(errors) == 0}}


@router.get("/preferences")
async def load_preferences():
    """加载用户偏好设置。

    API 端点：GET /api/ui/preferences

    请求参数：无

    返回格式（JSON）：
    {
        "success": true,
        "data": { ... }  // 用户偏好字段字典
    }

    Returns:
        当前保存的用户偏好。
    """
    persistence = _get_persistence()
    prefs = persistence.load()
    return {"success": True, "data": prefs.to_dict()}


@router.post("/preferences")
async def save_preferences(values: dict):
    """保存用户偏好设置（增量更新，仅修改传入的字段）。

    API 端点：POST /api/ui/preferences

    请求体（JSON）：偏好字段字典，只传需要修改的字段即可，未传入的字段保持不变。

    返回格式（JSON）：
    成功：
    {
        "success": true,
        "data": { ... }  // 更新后的完整偏好
    }
    失败：
    {
        "success": false,
        "error": {"message": "保存用户偏好失败"}
    }

    Args:
        values: 要更新的偏好字段字典。

    Returns:
        保存结果和更新后的偏好。
    """
    persistence = _get_persistence()
    prefs = persistence.load()

    for key, value in values.items():
        if hasattr(prefs, key):
            setattr(prefs, key, value)

    success = persistence.save(prefs)
    if success:
        return {"success": True, "data": prefs.to_dict()}
    else:
        return {"success": False, "error": {"message": "保存用户偏好失败"}}


@router.post("/preferences/reset")
async def reset_preferences():
    """重置用户偏好为默认值。

    API 端点：POST /api/ui/preferences/reset

    请求体：无

    返回格式（JSON）：
    {
        "success": true,
        "data": { ... }  // 重置后的默认偏好
    }

    Returns:
        重置后的默认偏好设置。
    """
    persistence = _get_persistence()
    prefs = persistence.reset()
    return {"success": True, "data": prefs.to_dict()}


@router.get("/layout")
async def get_layout():
    """获取折叠面板布局分组信息。

    API 端点：GET /api/ui/layout

    请求参数：无

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "groups": [
                {
                    "id": str,
                    "name": str,
                    "description": str,
                    "default_expanded": bool,
                    "priority": int,
                    "param_ids": list[str]
                }
            ]
        }
    }

    Returns:
        面板分组布局定义。
    """
    manager = _get_layout_manager()
    groups = []
    for group in manager.get_layout():
        groups.append(
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "default_expanded": group.default_expanded,
                "priority": group.priority,
                "param_ids": group.param_ids,
            }
        )

    return {"success": True, "data": {"groups": groups}}


class RestorePrefsRequest(BaseModel):
    """修复页偏好增量保存请求体。

    两个字段都可选、都采用"浅 merge + 覆盖"语义，前端只传变更了的字段即可。
    """

    values: dict | None = None
    unlock_state: dict | None = None


@router.get("/restore-preferences")
async def load_restore_preferences():
    """加载修复页最后一次保存的参数值 + 解锁状态快照。

    API 端点：GET /api/ui/restore-preferences

    返回（JSON，统一包装）：
        success: true
        data: {
            values: {<form_name>: <value>, ...}
            unlock_state: {<form_name>: true/false, ...}
        }
    """
    persistence = _get_persistence()
    values, unlocks = persistence.get_restore_form_values()
    return {"success": True, "data": {"values": values, "unlock_state": unlocks}}


@router.post("/restore-preferences")
async def patch_restore_preferences(req: RestorePrefsRequest):
    """增量保存修复页偏好（merge 更新，不会清空其它字段）。

    API 端点：POST /api/ui/restore-preferences
    请求体：
        {
            "values": {<form_name>: <value>, ...} | null,
            "unlock_state": {<form_name>: true/false, ...} | null,
        }
        任一字段 null 表示"本次不更新"，对应 dict 缺失的 key 也不会被删除。

    返回：保存后当前完整快照（data.values + data.unlock_state）。
    失败时返回 success=false，data=null，error.message 带提示。
    """
    persistence = _get_persistence()
    try:
        values, unlocks = persistence.patch_restore_form_values(
            values=req.values,
            unlock_state=req.unlock_state,
        )
        return {"success": True, "data": {"values": values, "unlock_state": unlocks}}
    except Exception as e:  # noqa: BLE001
        logger.exception("保存修复页偏好异常")
        return {"success": False, "data": None, "error": {"message": f"保存失败: {e}"}}
