#!/usr/bin/env python3
"""SeedVR2 - 批量任务断点续跑管理模块（借鉴 Image_MultiModel）。

本模块实现批量修复任务的断点续跑能力，在批量处理过程中定期保存进度，
应用崩溃/重启后可从上次断点恢复，跳过已完成的文件，避免重复处理。

存储格式: {checkpoint_dir}/{task_id}.json
{
    "task_id": "abc123...",
    "total": 32,
    "completed": 16,
    "completed_files": [
        {"path": "/abs/path/to/file1.png", "size": 102400, "mtime": 1234567890},
        ...
    ],
    "remaining": ["/abs/path/to/file17.png", ...],
    "config": {...},
    "media_type": "image"|"video",
    "use_model_size": "3b",
    "created_at": 1234567890,
    "updated_at": 1234567890
}

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, json, pathlib
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _file_fingerprint(path: str) -> dict[str, Any]:
    """获取文件指纹（路径 + 大小 + 修改时间），用于断点恢复时验证文件一致性。

    即使文件被移动，只要大小和修改时间匹配就能识别为同一文件。

    Args:
        path: 文件绝对路径。

    Returns:
        包含 path、size、mtime 的字典。文件不存在时 size 和 mtime 为 0。
    """
    try:
        stat = os.stat(path)
        return {"path": path, "size": stat.st_size, "mtime": stat.st_mtime}
    except (OSError, ValueError):
        return {"path": path, "size": 0, "mtime": 0}


class TaskCheckpoint:
    """断点续跑管理器。

    在批量处理过程中定期保存进度到 JSON 文件，
    应用崩溃重启后可从 checkpoint 恢复未完成任务。

    Attributes:
        checkpoint_dir: checkpoint 文件存储目录路径。
    """

    def __init__(self, checkpoint_dir: str = "data/checkpoints") -> None:
        """初始化断点续跑管理器。

        Args:
            checkpoint_dir: checkpoint 文件存储目录路径，不存在时自动创建。
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        """获取指定任务 ID 的 checkpoint 文件路径。

        Args:
            task_id: 批量任务 ID。

        Returns:
            checkpoint 文件的 Path 对象。
        """
        return self.checkpoint_dir / f"{task_id}.json"

    def save_checkpoint(
        self,
        task_id: str,
        total: int,
        completed_files: list[dict[str, Any]],
        remaining: list[str],
        config: dict[str, Any],
        media_type: str = "image",
        use_model_size: str = "3b",
    ) -> None:
        """保存/更新批量任务 checkpoint。

        在批量处理过程中每处理完一个文件后调用，记录已完成文件列表和剩余文件列表。

        Args:
            task_id: 批量任务 ID。
            total: 文件总数。
            completed_files: 已完成文件的信息列表，每项包含 path/size/mtime 指纹。
            remaining: 剩余待处理文件路径列表。
            config: 推理参数配置字典。
            media_type: 媒体类型 "image" 或 "video"。
            use_model_size: 模型尺寸标识。
        """
        data = {
            "task_id": task_id,
            "total": total,
            "completed": len(completed_files),
            "completed_files": completed_files,
            "remaining": remaining,
            "config": config,
            "media_type": media_type,
            "use_model_size": use_model_size,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        path = self._path(task_id)
        if path.exists():
            # 保留原始创建时间
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                data["created_at"] = old.get("created_at", time.time())
            except Exception:
                pass
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(f"Checkpoint 已保存: {task_id} ({len(completed_files)}/{total})")

    def load_checkpoint(self, task_id: str) -> dict[str, Any] | None:
        """加载指定任务的 checkpoint。

        Args:
            task_id: 批量任务 ID。

        Returns:
            checkpoint 数据字典，不存在或加载失败时返回 None。
        """
        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"Checkpoint 已加载: {task_id} " f"({data.get('completed', 0)}/{data.get('total', 0)})")
            return data
        except Exception as e:
            logger.warning(f"加载 checkpoint 失败 {task_id}: {e}")
            return None

    def remove_checkpoint(self, task_id: str) -> bool:
        """删除指定任务的 checkpoint（任务完成后调用）。

        Args:
            task_id: 批量任务 ID。

        Returns:
            bool: 成功删除返回 True，文件不存在返回 False。
        """
        path = self._path(task_id)
        if path.exists():
            path.unlink()
            logger.debug(f"Checkpoint 已删除: {task_id}")
            return True
        return False

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """列出所有未完成的 checkpoint。

        扫描 checkpoint 目录，返回所有 completed < total 的 checkpoint。

        Returns:
            未完成 checkpoint 数据列表，每项为一个字典。
        """
        results: list[dict[str, Any]] = []
        for p in self.checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("completed", 0) < data.get("total", 0):
                    results.append(data)
            except Exception:
                continue
        return results

    def should_checkpoint(self, completed_count: int, checkpoint_every: int = 1) -> bool:
        """判断是否需要写 checkpoint。

        Args:
            completed_count: 已完成文件数。
            checkpoint_every: 每处理多少个文件写一次 checkpoint。

        Returns:
            bool: 需要写 checkpoint 时返回 True。
        """
        return completed_count > 0 and completed_count % checkpoint_every == 0

    def get_completed_paths(self, task_id: str) -> set[str]:
        """获取指定任务已完成的文件路径集合。

        用于批量恢复时跳过已处理的文件。

        Args:
            task_id: 批量任务 ID。

        Returns:
            已完成文件路径的集合，无 checkpoint 时返回空集合。
        """
        data = self.load_checkpoint(task_id)
        if data is None:
            return set()
        return {item["path"] for item in data.get("completed_files", []) if "path" in item}

    def get_completed_fingerprints(self, task_id: str) -> dict[str, dict[str, Any]]:
        """获取指定任务已完成文件的指纹映射。

        路径 -> {size, mtime} 的映射，用于路径变更后的指纹匹配。

        Args:
            task_id: 批量任务 ID。

        Returns:
            路径到指纹的映射字典，无 checkpoint 时返回空字典。
        """
        data = self.load_checkpoint(task_id)
        if data is None:
            return {}
        return {item["path"]: item for item in data.get("completed_files", []) if "path" in item}
