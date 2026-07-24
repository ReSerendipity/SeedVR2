#!/usr/bin/env python3
"""Klar - 设置管理路由"""
import asyncio
import logging
import os
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bin.integrated_app.config import save_config
from bin.integrated_app.dependencies import (
    get_config,
    get_i18n,
    get_model_manager,
)
from bin.integrated_app.i18n import I18n
from bin.integrated_app.model_manager import ModelManager

logger = logging.getLogger(__name__)
router = APIRouter()

# 允许的根目录列表（为空则不限制）
ALLOWED_ROOT_DIRS: list[str] = []


def validate_path(path: str, allowed_roots: list[str] | None = None) -> str:
    """验证路径安全性，防止路径遍历攻击

    - 使用 os.path.realpath() 解析真实路径
    - 拒绝包含 '..' 的路径
    - 可选限制到允许的根目录列表
    """
    if not path:
        raise HTTPException(status_code=400, detail="路径为空")

    # 拒绝包含路径遍历的原始输入
    if ".." in path:
        raise HTTPException(status_code=400, detail="路径不允许包含 '..'")

    # 解析真实路径（消除符号链接等）
    real_path = os.path.realpath(path)

    # 再次检查解析后的路径是否包含路径遍历
    if ".." in real_path:
        raise HTTPException(status_code=400, detail="解析后的路径不允许包含 '..'")

    # 如果配置了允许的根目录，检查路径是否在允许范围内
    roots = allowed_roots if allowed_roots is not None else ALLOWED_ROOT_DIRS
    if roots and not any(real_path.startswith(os.path.realpath(r)) for r in roots):
        raise HTTPException(status_code=403, detail="路径不在允许的目录范围内")

    return real_path


class ModelLoadRequest(BaseModel):
    size: str = "3b"
    device: str | None = None
    precision: str | None = None  # fp16 / fp8, 默认自动选择


class ModelSwitchRequest(BaseModel):
    size: str = "3b"
    device: str | None = None
    precision: str | None = None  # fp16 / fp8, 默认自动选择


class SettingsUpdateRequest(BaseModel):
    default_model_size: str | None = None
    default_precision: str | None = None
    default_locale: str | None = None
    gpu_backend: str | None = None
    memory_strategy: str | None = None
    enable_fp16: bool | None = None
    auto_load: bool | None = None
    default_resolution_h: int | None = None
    default_resolution_w: int | None = None
    seed: int | None = None


@router.get("/settings")
async def get_settings(config: dict = Depends(get_config)):
    """获取当前设置（含用户偏好）"""
    # 加载用户偏好
    try:
        from bin.integrated_app.optimization.webui_enhancement import SettingsPersistence
        persistence = SettingsPersistence()
        user_prefs = persistence.load().to_dict()
    except Exception:
        user_prefs = {}

    return JSONResponse({
        "model": config.get("model", {}),
        "gpu": config.get("gpu", {}),
        "i18n": config.get("i18n", {}),
        "restore": config.get("restore", {}),
        "user_preferences": user_prefs,
    })


@router.post("/settings")
async def update_settings(
    settings: SettingsUpdateRequest,
    config: dict = Depends(get_config),
):
    """更新设置"""
    if settings.default_model_size is not None:
        config.setdefault("model", {})["default_size"] = settings.default_model_size
    if settings.default_precision is not None:
        config.setdefault("model", {})["default_precision"] = settings.default_precision
    if settings.auto_load is not None:
        config.setdefault("model", {})["auto_load"] = settings.auto_load
    if settings.default_locale is not None:
        config.setdefault("i18n", {})["default_locale"] = settings.default_locale
    if settings.gpu_backend is not None:
        config.setdefault("gpu", {})["backend"] = settings.gpu_backend
    if settings.memory_strategy is not None:
        config.setdefault("gpu", {})["memory_strategy"] = settings.memory_strategy
    if settings.enable_fp16 is not None:
        config.setdefault("gpu", {})["enable_fp16"] = settings.enable_fp16
    if settings.default_resolution_h is not None:
        config.setdefault("restore", {})["default_resolution_h"] = settings.default_resolution_h
    if settings.default_resolution_w is not None:
        config.setdefault("restore", {})["default_resolution_w"] = settings.default_resolution_w
    if settings.seed is not None:
        config.setdefault("restore", {})["seed"] = settings.seed

    await run_in_threadpool(save_config, config)

    # 同步保存用户偏好到 user_preferences 段
    try:
        from bin.integrated_app.optimization.webui_enhancement import SettingsPersistence
        persistence = SettingsPersistence()
        prefs = persistence.load()
        # 将设置值映射到偏好
        if settings.default_resolution_h is not None:
            prefs.default_resolution = settings.default_resolution_h
        if settings.seed is not None:
            prefs.default_seed = settings.seed
        persistence.save(prefs)
    except Exception as e:
        logger.debug(f"用户偏好同步保存跳过: {e}")

    return JSONResponse({"status": "ok", "message": "设置已更新"})


@router.post("/model/load")
async def load_model(
    req: ModelLoadRequest,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """加载模型"""
    try:
        result = await model_manager.load_model(
            model_size=req.size, device=req.device, precision=req.precision
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"模型加载失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.post("/model/unload")
async def unload_model(model_manager: ModelManager = Depends(get_model_manager)):
    """卸载模型"""
    try:
        result = await model_manager.unload_model()
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"模型卸载失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.post("/model/switch")
async def switch_model(
    req: ModelSwitchRequest,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """切换模型"""
    try:
        result = await model_manager.switch_model(
            model_size=req.size, device=req.device, precision=req.precision
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"模型切换失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.get("/model/status")
async def model_status(model_manager: ModelManager = Depends(get_model_manager)):
    """获取模型状态"""
    return JSONResponse(model_manager.get_status())


@router.post("/locale")
async def set_locale(
    request: Request,
    i18n: I18n = Depends(get_i18n),
    config: dict = Depends(get_config),
):
    """切换语言"""
    try:
        body = await request.json()
        locale = body.get("locale", "zh")
    except Exception:
        locale = "zh"

    i18n.set_locale(locale)

    # 同时保存到配置文件
    config.setdefault("i18n", {})["default_locale"] = locale
    await run_in_threadpool(save_config, config)

    return JSONResponse({
        "status": "ok",
        "locale": locale,
        "message": f"语言已切换为 {i18n.get_locale_name(locale)}",
    })


@router.get("/locales")
async def get_locales(i18n: I18n = Depends(get_i18n)):
    """获取可用语言列表"""
    locales = []
    for code in i18n.available_locales:
        locales.append({
            "code": code,
            "name": i18n.get_locale_name(code),
        })
    return JSONResponse({
        "current": i18n.current_locale,
        "locales": locales,
    })


@router.get("/browse-dir")
async def browse_directory(path: str = "", show_files: bool = False):
    """浏览服务器本地目录，返回子目录列表（用于文件夹选择器）

    参数:
        path: 要浏览的目录路径，为空则返回根驱动器列表
        show_files: 是否同时显示文件
    """
    if not path:
        # Windows: 返回可用驱动器列表
        drives = []
        if os.name == "nt":
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if await asyncio.to_thread(os.path.exists, drive):
                    drives.append({"name": drive, "path": drive, "type": "drive"})
        else:
            drives.append({"name": "/", "path": "/", "type": "drive"})
        return JSONResponse({"current_path": "", "items": drives})

    # 路径安全验证
    path = validate_path(path)

    # 验证路径存在且是目录
    if not await asyncio.to_thread(os.path.exists, path):
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not await asyncio.to_thread(os.path.isdir, path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    items = []
    try:
        entries = await asyncio.to_thread(
            lambda: sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}") from e

    for entry in entries:
        try:
            if entry.is_dir():
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "directory",
                })
            elif show_files and entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                size = (await asyncio.to_thread(entry.stat)).st_size
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "file",
                    "ext": ext,
                    "size": size,
                })
        except (PermissionError, OSError):
            continue

    # 返回父目录信息
    parent = os.path.dirname(path.rstrip("/\\"))
    if parent == path.rstrip("/\\"):
        parent = ""  # 已经是根目录

    return JSONResponse({
        "current_path": path,
        "parent_path": parent,
        "items": items,
    })


@router.post("/open-explorer")
async def open_in_explorer(request: Request):
    """在系统资源管理器中打开指定路径"""
    body = await request.json()
    path = body.get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="路径为空")

    # 路径安全验证
    path = validate_path(path)

    if not await asyncio.to_thread(os.path.exists, path):
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")

    try:
        if sys.platform == "win32":
            await run_in_threadpool(os.startfile, path)
        elif sys.platform == "darwin":
            await run_in_threadpool(subprocess.Popen, ["open", path])
        else:
            await run_in_threadpool(subprocess.Popen, ["xdg-open", path])
        return JSONResponse({"success": True, "message": f"已打开: {path}"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开失败: {str(e)}") from e
