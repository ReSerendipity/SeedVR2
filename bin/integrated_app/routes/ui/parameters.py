#!/usr/bin/env python3
"""UI 参数面板与用户偏好 API 路由模块。

暴露 webui_enhancement 模块的后端框架组件，为前端提供：
- 参数定义查询
- 用户偏好设置的持久化（加载/保存/重置）
- 折叠面板布局分组信息

API 端点：
- GET /api/ui/parameters: 获取所有参数定义
- GET /api/ui/preferences: 加载用户偏好
- POST /api/ui/preferences: 保存用户偏好
- POST /api/ui/preferences/reset: 重置用户偏好为默认值
- GET /api/ui/layout: 获取折叠面板布局分组

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_optimizer():
    """获取参数面板优化器实例（内部懒加载函数）。

    延迟导入 create_default_parameter_panel，避免循环依赖和启动时不必要的加载。

    Returns:
        参数面板优化器实例。
    """
    from bin.integrated_app.optimization.webui_enhancement import create_default_parameter_panel

    return create_default_parameter_panel()


def _get_persistence():
    """获取设置持久化管理器实例（内部懒加载函数）。

    Returns:
        SettingsPersistence 实例。
    """
    from bin.integrated_app.optimization.webui_enhancement import SettingsPersistence

    return SettingsPersistence()


def _get_layout_manager():
    """获取折叠面板布局管理器实例（内部懒加载函数）。

    Returns:
        AccordionLayoutManager 实例。
    """
    from bin.integrated_app.optimization.webui_enhancement import AccordionLayoutManager

    return AccordionLayoutManager()


@router.get("/parameters")
async def get_parameters():
    """获取所有参数定义。

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
            ]
        }
    }

    Returns:
        包含参数定义的字典。
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

    return {"success": True, "data": {"parameters": params}}


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
