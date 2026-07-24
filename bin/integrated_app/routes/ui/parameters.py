"""UI 参数面板与用户偏好 API 路由

暴露 webui_enhancement 模块的后端框架组件:
- 参数定义与预设组合
- 用户偏好持久化
- 折叠面板布局
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_optimizer():
    """获取参数面板优化器实例"""
    from bin.integrated_app.optimization.webui_enhancement import create_default_parameter_panel
    return create_default_parameter_panel()


def _get_persistence():
    """获取设置持久化管理器实例"""
    from bin.integrated_app.optimization.webui_enhancement import SettingsPersistence
    return SettingsPersistence()


def _get_layout_manager():
    """获取折叠面板布局管理器实例"""
    from bin.integrated_app.optimization.webui_enhancement import AccordionLayoutManager
    return AccordionLayoutManager()


# ---------------------------------------------------------------------------
# 参数定义与预设
# ---------------------------------------------------------------------------

@router.get("/parameters")
async def get_parameters():
    """获取所有参数定义和预设组合

    返回:
        parameters: 参数定义列表
        presets: 预设组合列表 (含推荐范围)
    """
    optimizer = _get_optimizer()

    params = []
    for p in optimizer.get_all_params():
        params.append({
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
        })

    presets = []
    for preset in optimizer.get_presets():
        presets.append({
            "name": preset.name,
            "description": preset.description,
            "values": preset.preset_values,
            "recommended_ranges": {
                k: {"min": v[0], "max": v[1]}
                for k, v in preset.recommended_ranges.items()
            },
            "use_case": preset.use_case,
        })

    return {"success": True, "data": {"parameters": params, "presets": presets}}


@router.get("/parameters/recommendations")
async def get_recommendations(cfg_scale: float = 3.0, denoising_strength: float = 0.6, steps: int = 20):
    """根据当前参数值获取推荐预设

    返回按匹配度排序的推荐列表
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
        result.append({
            "name": preset.name,
            "description": preset.description,
            "values": preset.preset_values,
            "match_score": rec["match_score"],
            "use_case": rec["use_case"],
        })

    return {"success": True, "data": {"recommendations": result}}


@router.post("/parameters/validate")
async def validate_parameters(values: dict):
    """验证参数值是否在合法范围内

    请求体: {"cfg_scale": 3.0, "denoising_strength": 0.6, ...}
    返回: errors 字典 (空表示全部合法)
    """
    optimizer = _get_optimizer()
    errors = optimizer.validate_values(values)
    return {"success": True, "data": {"errors": errors, "valid": len(errors) == 0}}


# ---------------------------------------------------------------------------
# 用户偏好持久化
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def load_preferences():
    """加载用户偏好设置"""
    persistence = _get_persistence()
    prefs = persistence.load()
    return {"success": True, "data": prefs.to_dict()}


@router.post("/preferences")
async def save_preferences(values: dict):
    """保存用户偏好设置

    请求体: 偏好字段字典，仅传需要修改的字段
    """
    persistence = _get_persistence()
    prefs = persistence.load()

    # 只更新传入的字段
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
    """重置用户偏好为默认值"""
    persistence = _get_persistence()
    prefs = persistence.reset()
    return {"success": True, "data": prefs.to_dict()}


# ---------------------------------------------------------------------------
# 折叠面板布局
# ---------------------------------------------------------------------------

@router.get("/layout")
async def get_layout():
    """获取折叠面板布局分组信息"""
    manager = _get_layout_manager()
    groups = []
    for group in manager.get_layout():
        groups.append({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "default_expanded": group.default_expanded,
            "priority": group.priority,
            "param_ids": group.param_ids,
        })

    return {"success": True, "data": {"groups": groups}}
