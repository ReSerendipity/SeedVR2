#!/usr/bin/env python3
"""Klar - 文件夹扫描路由

递归扫描指定文件夹下的所有图片/视频文件。

SECURITY [D4-1] [B1-1]: 路径安全策略重写
- 原实现使用 _SYSTEM_BLOCKED_DIRS 黑名单，违反 AGENTS.md 硬约束
  （"文件夹扫描必须经 security/path_guard.py 白名单校验，禁止任意目录遍历"）
- 黑名单存在不可枚举问题：系统保护目录无法穷举，且无法防御
  用户私有目录（如 D:\\secrets）的文件清单泄露
- 改为白名单机制：仅允许扫描 config.runtime.security.allowed_base_dirs
  子树内的路径，与 download_result 端点保持一致的安全模型

ROBUSTNESS [E2-1] [C5-2]: 资源耗尽防护
- 原实现对递归深度和文件总数无限制，扫描深目录或大目录可能
  导致内存爆满或长时间阻塞事件循环
- 增加 max_depth / max_files / max_total_size_mb 三重防护，
  超限时返回 413 并提示用户缩小范围
"""
import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from bin.integrated_app.dependencies import get_config
from bin.integrated_app.routes.restore import common
from bin.integrated_app.security.path_guard import build_default_path_guard

logger = logging.getLogger(__name__)
router = APIRouter()

# REFACTOR [A3-1]: 资源耗尽防护常量外置，避免魔法数字
# 默认值与 config.runtime.security 对齐；可通过 config 覆盖
_DEFAULT_MAX_SCAN_DEPTH = 32
_DEFAULT_MAX_SCAN_FILES = 50000
_DEFAULT_MAX_SCAN_TOTAL_SIZE_MB = 50_000  # 50 GB 元数据扫描上限


@router.get("/scan-folder")
async def scan_media_folder(
    folder_path: str,
    start_index: int = 0,
    config: dict = Depends(get_config),
):
    """递归扫描指定文件夹下的所有图片/视频文件

    SECURITY [D4-1]: 使用 PathGuard 白名单校验，仅允许扫描
    config.runtime.security.allowed_base_dirs 子树内的路径。
    """
    folder = Path(folder_path)

    # SECURITY [D4-1]: 白名单校验，替代原黑名单 (_SYSTEM_BLOCKED_DIRS)
    # 白名单与 download_result 端点共用 build_default_path_guard，
    # 确保扫描与下载的安全模型一致
    security_cfg = config.get("runtime", {}).get("security", {})
    allowed_dirs = security_cfg.get(
        "allowed_base_dirs", ["outputs/", "data/uploads/"]
    )
    path_guard = build_default_path_guard(os.getcwd(), allowed_dirs)
    if not path_guard.is_safe_path(folder):
        # SECURITY [D6-1]: 不回显用户输入的路径，防止信息探测
        logger.warning(f"扫描路径被白名单拒绝: {folder}")
        raise HTTPException(
            status_code=403,
            detail="不允许扫描该路径（不在允许的目录范围内）",
        )

    if not await asyncio.to_thread(folder.exists):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    if not await asyncio.to_thread(folder.is_dir):
        raise HTTPException(status_code=400, detail="路径不是文件夹")

    # REFACTOR [A3-1]: 资源限制参数从 config 读取，无配置时使用安全默认值
    max_depth = security_cfg.get("scan_max_depth", _DEFAULT_MAX_SCAN_DEPTH)
    max_files = security_cfg.get("scan_max_files", _DEFAULT_MAX_SCAN_FILES)
    max_total_size_mb = security_cfg.get(
        "scan_max_total_size_mb", _DEFAULT_MAX_SCAN_TOTAL_SIZE_MB
    )
    max_total_size_bytes = max_total_size_mb * 1024 * 1024

    media_files = []
    all_exts = common.IMAGE_EXTENSIONS | common.VIDEO_EXTENSIONS
    total_size = 0
    truncated = False

    # ROBUSTNESS [E2-1] [C5-2]: 限制递归深度与文件数量，防止资源耗尽
    # os.walk 默认不限制深度，深目录可能触发 Windows MAX_PATH 限制或内存爆满
    for root, _dirs, files in await asyncio.to_thread(
        lambda: list(_limited_walk(folder, max_depth))
    ):
        if len(media_files) >= max_files:
            truncated = True
            logger.warning(
                f"扫描文件数超过上限 {max_files}，已截断 (folder={folder})"
            )
            break
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in all_exts:
                continue
            full_path = os.path.join(root, fname)
            try:
                size = await asyncio.to_thread(os.path.getsize, full_path)
            except OSError:
                size = 0
            # ROBUSTNESS [C5-2]: 累计大小超限则停止，避免内存累积
            total_size += size
            if total_size > max_total_size_bytes:
                truncated = True
                logger.warning(
                    f"扫描累计大小超过 {max_total_size_mb}MB，已截断 (folder={folder})"
                )
                break
            media_files.append({
                "path": full_path,
                "name": fname,
                "size": size,
                "relative": os.path.relpath(full_path, folder),
                "type": "image" if ext in common.IMAGE_EXTENSIONS else "video",
            })
            if len(media_files) >= max_files:
                truncated = True
                logger.warning(
                    f"扫描文件数超过上限 {max_files}，已截断 (folder={folder})"
                )
                break
        if truncated:
            break

    media_files.sort(key=lambda x: x["relative"])
    total = len(media_files)
    sliced = media_files[start_index:] if start_index > 0 else media_files

    return JSONResponse({
        "total": total,
        "returned": len(sliced),
        "start_index": start_index,
        "files": sliced,
        # ROBUSTNESS: 通知调用方结果被截断，前端可提示用户缩小范围
        "truncated": truncated,
        "limits": {
            "max_files": max_files,
            "max_depth": max_depth,
            "max_total_size_mb": max_total_size_mb,
        },
    })


def _limited_walk(root: Path, max_depth: int):
    """限制递归深度的 os.walk 生成器

    ROBUSTNESS [E2-1]: os.walk 默认无深度限制，深目录可能导致：
    - Windows MAX_PATH (260) 路径过长错误
    - 符号链接循环导致无限递归
    - 内存累积所有目录条目

    Args:
        root: 扫描根目录
        max_depth: 最大递归深度（0 表示仅根目录，1 表示允许 1 层子目录）

    Yields:
        与 os.walk 相同的 (dirpath, dirnames, filenames) 元组
    """
    # REFACTOR: 使用栈模拟而非 os.walk，便于精确控制深度
    # 同时避免 os.walk 在 Windows 上对长路径的潜在问题
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except (OSError, PermissionError) as e:
            # ROBUSTNESS [E2-2]: 跳过无权限访问的目录，不让单目录失败导致整个扫描失败
            logger.debug(f"跳过无法访问的目录: {current} ({e})")
            continue

        dirs = []
        files = []
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                # SECURITY: follow_symlinks=False 防止符号链接绕过白名单
                dirs.append(entry.name)
                if depth < max_depth:
                    stack.append((entry.path, depth + 1))
            elif entry.is_file(follow_symlinks=False):
                files.append(entry.name)

        yield (current, dirs, files)
