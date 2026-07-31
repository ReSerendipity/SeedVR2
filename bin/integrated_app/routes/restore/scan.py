#!/usr/bin/env python3
"""文件夹扫描路由模块。

提供递归扫描指定文件夹下图片/视频文件的 API 端点，
包含完整的路径安全校验（白名单机制）和资源耗尽防护。

安全措施：
- 使用 PathGuard 白名单校验，仅允许扫描配置中允许的目录子树
- 不回显被拒绝的路径，防止信息探测
- 限制递归深度、文件总数、累计扫描大小三重防护
- follow_symlinks=False 防止符号链接绕过白名单

API 端点：
- GET /api/restore/scan-folder: 递归扫描媒体文件夹

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
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

_DEFAULT_MAX_SCAN_DEPTH = 32
_DEFAULT_MAX_SCAN_FILES = 50000
_DEFAULT_MAX_SCAN_TOTAL_SIZE_MB = 50_000


@router.get("/scan-folder")
async def scan_media_folder(
    folder_path: str,
    start_index: int = 0,
    config: dict = Depends(get_config),
):
    """递归扫描指定文件夹下的所有图片/视频文件。

    API 端点：GET /api/restore/scan-folder

    请求参数：
    - folder_path (query, required): 要扫描的文件夹绝对路径
    - start_index (query, optional): 分页起始索引，默认 0

    返回格式（JSON）：
    {
        "total": int,           // 匹配的媒体文件总数
        "returned": int,        // 本次返回的文件数
        "start_index": int,     // 本次起始索引
        "files": [              // 文件列表
            {
                "path": str,    // 绝对路径
                "name": str,    // 文件名
                "size": int,    // 文件大小（字节）
                "relative": str,// 相对根目录路径
                "type": "image"|"video"
            }
        ],
        "truncated": bool,      // 是否因达到限制而截断
        "limits": {             // 本次使用的限制参数
            "max_files": int,
            "max_depth": int,
            "max_total_size_mb": int
        }
    }

    错误响应：
    - 403: 路径不在白名单允许范围内
    - 404: 文件夹不存在
    - 400: 路径不是文件夹
    - 413: 扫描超出资源限制（隐式通过 truncated 返回）

    Args:
        folder_path: 要扫描的文件夹路径。
        start_index: 分页起始索引。
        config: 应用配置（通过依赖注入）。

    Returns:
        JSONResponse 包含扫描结果。

    Raises:
        HTTPException: 路径不合法或文件夹不存在时抛出。
    """
    folder = Path(folder_path)

    security_cfg = config.get("runtime", {}).get("security", {})
    allowed_dirs = security_cfg.get(
        "allowed_base_dirs", ["outputs/", "data/uploads/"]
    )
    path_guard = build_default_path_guard(os.getcwd(), allowed_dirs)
    if not path_guard.is_safe_path(folder):
        logger.warning(f"扫描路径被白名单拒绝: {folder}")
        raise HTTPException(
            status_code=403,
            detail="不允许扫描该路径（不在允许的目录范围内）",
        )

    if not await asyncio.to_thread(folder.exists):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    if not await asyncio.to_thread(folder.is_dir):
        raise HTTPException(status_code=400, detail="路径不是文件夹")

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
        "truncated": truncated,
        "limits": {
            "max_files": max_files,
            "max_depth": max_depth,
            "max_total_size_mb": max_total_size_mb,
        },
    })


def _limited_walk(root: Path, max_depth: int):
    """限制递归深度的目录遍历生成器（内部函数）。

    使用栈模拟 os.walk，精确控制递归深度，避免：
    - Windows MAX_PATH (260) 路径过长错误
    - 符号链接循环导致无限递归
    - 深目录造成的内存累积
    无权限访问的目录会被跳过，不影响整体扫描。

    Args:
        root: 扫描根目录。
        max_depth: 最大递归深度（0 表示仅根目录，1 表示允许 1 层子目录）。

    Yields:
        与 os.walk 格式相同的 (dirpath, dirnames, filenames) 元组。
    """
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except (OSError, PermissionError) as e:
            logger.debug(f"跳过无法访问的目录: {current} ({e})")
            continue

        dirs = []
        files = []
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry.name)
                if depth < max_depth:
                    stack.append((entry.path, depth + 1))
            elif entry.is_file(follow_symlinks=False):
                files.append(entry.name)

        yield (current, dirs, files)
