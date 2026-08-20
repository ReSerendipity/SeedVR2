#!/usr/bin/env python3
"""SeedVR2 - 文件缓存与内存缓存管理模块

提供两类缓存实现:
1. FileCache: 上传文件的磁盘缓存，支持大文件异步流式写入、TTL过期自动清理
2. LRUCache: 基于 OrderedDict 的固定容量 LRU 内存缓存，线程安全
3. AdaptiveLRUCache: 根据 GPU 显存使用率自适应调整容量的 LRU 缓存，
   在高 GPU 负载时自动收缩以释放内存，低负载时扩展以提高命中率

缓存设计遵循以下原则:
- 大文件流式写入，避免阻塞 asyncio 事件循环
- 自动过期清理，防止磁盘空间无限增长
- 线程安全，支持多线程并发访问
- GPU 感知，自适应调整内存缓存容量以配合推理任务
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileCache:
    """上传文件磁盘缓存管理器

    管理用户上传文件的临时存储，提供:
    - 唯一文件名生成（时间戳 + UUID + 原始扩展名）
    - 大文件/小文件差异化写入策略（大文件异步流式，小文件一次性读取）
    - TTL 过期文件自动清理（后台任务，默认每小时执行一次）
    - 缓存统计信息查询

    Attributes:
        cache_dir: 缓存文件存储目录路径。
        ttl: 文件存活时间（秒），超过此时间未访问的文件将被清理。
        large_file_threshold: 大文件阈值（字节），超过则使用流式写入。
        chunk_size: 流式写入时的块大小（字节）。
        _cleanup_task: 后台自动清理的 asyncio Task 引用。
    """

    def __init__(
        self,
        cache_dir: str = "data/uploads",
        ttl: int = 86400,
        *,
        large_file_threshold_mb: int = 10,
        chunk_size_bytes: int = 8192,
    ):
        """初始化文件缓存管理器。

        Args:
            cache_dir: 缓存目录路径，不存在时自动创建。
            ttl: 文件存活时间（秒），默认 86400 秒（24小时）。
            large_file_threshold_mb: 大文件阈值（MB），超过此大小使用流式写入，避免阻塞事件循环。
            chunk_size_bytes: 流式写入的块大小（字节），默认 8192（8KB）。
        """
        self.cache_dir = cache_dir
        self.ttl = ttl
        # REFACTOR: 外置原本硬编码的魔法数字 (A4/F1)，支持从 config.runtime.upload 注入
        self.large_file_threshold = large_file_threshold_mb * 1024 * 1024
        self.chunk_size = chunk_size_bytes
        self._cleanup_task: asyncio.Task | None = None
        os.makedirs(cache_dir, exist_ok=True)

    def generate_unique_filename(self, original_filename: str) -> str:
        """生成唯一文件名，保留原始扩展名

        Args:
            original_filename: 原始文件名

        Returns:
            唯一文件名字符串
        """
        ext = Path(original_filename).suffix or ".bin"
        unique_id = uuid.uuid4().hex[:12]
        timestamp = int(time.time())
        return f"{timestamp}_{unique_id}{ext}"

    def get_cache_path(self, filename: str) -> str:
        """获取缓存文件的完整路径。

        Args:
            filename: 缓存文件名。

        Returns:
            缓存文件的绝对/相对完整路径（拼接 cache_dir 与 filename）。
        """
        return os.path.join(self.cache_dir, filename)

    async def save_upload_file(self, upload_file, sub_dir: str | None = None) -> tuple[str, str]:
        """保存上传文件到缓存

        Args:
            upload_file: FastAPI UploadFile 对象
            sub_dir: 子目录（可选）

        Returns:
            (保存的文件名, 完整路径)
        """
        target_dir = self.cache_dir
        if sub_dir:
            target_dir = os.path.join(self.cache_dir, sub_dir)
            os.makedirs(target_dir, exist_ok=True)

        unique_name = self.generate_unique_filename(upload_file.filename or "upload")
        file_path = os.path.join(target_dir, unique_name)

        # 尝试获取文件大小以决定写入策略
        file_size = 0
        if hasattr(upload_file, "size") and upload_file.size is not None:
            file_size = upload_file.size
        elif hasattr(upload_file, "file") and hasattr(upload_file.file, "seek") and hasattr(upload_file.file, "tell"):
            try:
                pos = upload_file.file.tell()
                upload_file.file.seek(0, 2)  # seek to end
                file_size = upload_file.file.tell()
                upload_file.file.seek(pos)  # restore position
            except (OSError, ValueError):
                file_size = 0

        if file_size > self.large_file_threshold:
            # OPTIMIZE: 大文件异步流式写入。
            # 原实现使用 upload_file.file.read() 同步阻塞事件循环（注释却写着"异步"）；
            # 改为 await upload_file.read() 走 asyncio.to_thread，真正不阻塞 (E7/C10)
            import aiofiles

            await upload_file.seek(0)
            async with aiofiles.open(file_path, "wb") as f:
                while True:
                    chunk = await upload_file.read(self.chunk_size)
                    if not chunk:
                        break
                    await f.write(chunk)
            logger.info(f"文件已缓存(异步写入): {file_path} ({file_size} bytes)")
        else:
            # 小文件：一次性读取
            content = await upload_file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            logger.info(f"文件已缓存: {file_path} ({len(content)} bytes)")

        return unique_name, file_path

    def save_bytes(self, data: bytes, original_filename: str = "upload", sub_dir: str | None = None) -> tuple[str, str]:
        """保存字节数据到缓存

        Args:
            data: 文件数据
            original_filename: 原始文件名（用于获取扩展名）
            sub_dir: 子目录（可选）

        Returns:
            (保存的文件名, 完整路径)
        """
        target_dir = self.cache_dir
        if sub_dir:
            target_dir = os.path.join(self.cache_dir, sub_dir)
            os.makedirs(target_dir, exist_ok=True)

        unique_name = self.generate_unique_filename(original_filename)
        file_path = os.path.join(target_dir, unique_name)

        with open(file_path, "wb") as f:
            f.write(data)

        logger.info(f"数据已缓存: {file_path} ({len(data)} bytes)")
        return unique_name, file_path

    def file_exists(self, filename: str) -> bool:
        """检查缓存文件是否存在。

        Args:
            filename: 缓存文件名。

        Returns:
            文件存在返回 True，否则返回 False。
        """
        return os.path.exists(os.path.join(self.cache_dir, filename))

    def get_file_path(self, filename: str, sub_dir: str | None = None) -> str | None:
        """获取缓存文件路径，不存在则返回 None。

        Args:
            filename: 缓存文件名。
            sub_dir: 可选的子目录名称。

        Returns:
            文件存在时返回完整路径，否则返回 None。
        """
        if sub_dir:
            path = os.path.join(self.cache_dir, sub_dir, filename)
        else:
            path = os.path.join(self.cache_dir, filename)
        return path if os.path.exists(path) else None

    def delete_file(self, file_path: str) -> bool:
        """删除指定缓存文件。

        Args:
            file_path: 要删除的文件完整路径。

        Returns:
            删除成功返回 True，文件不存在或删除失败返回 False。
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"缓存文件已删除: {file_path}")
                return True
            return False
        except OSError as e:
            logger.error(f"删除缓存文件失败: {e}")
            return False

    def cleanup_expired(self) -> int:
        """清理过期文件

        使用 os.scandir 递归遍历，比 os.walk 更高效（DirEntry 缓存文件属性）。

        Returns:
            清理的文件数量
        """
        if not os.path.exists(self.cache_dir):
            return 0

        now = time.time()
        cleaned = 0

        cleaned += self._cleanup_expired_in_dir(self.cache_dir, now)

        if cleaned > 0:
            logger.info(f"清理了 {cleaned} 个过期缓存文件")

        return cleaned

    def _cleanup_expired_in_dir(self, dir_path: str, now: float) -> int:
        """递归清理指定目录下的过期文件（内部辅助方法）。

        Args:
            dir_path: 要扫描的目录路径。
            now: 当前时间戳，用于判断文件是否过期。

        Returns:
            清理的文件数量。
        """
        cleaned = 0
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        cleaned += self._cleanup_expired_in_dir(entry.path, now)
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            if now - mtime > self.ttl:
                                os.remove(entry.path)
                                cleaned += 1
                        except OSError:
                            continue
        except OSError:
            pass
        return cleaned

    def start_cleanup_task(self, interval: int = 3600):
        """启动后台自动清理任务

        Args:
            interval: 清理间隔（秒），默认1小时
        """

        async def _cleanup_loop():
            while True:
                try:
                    self.cleanup_expired()
                except Exception as e:
                    logger.error(f"自动清理失败: {e}")
                await asyncio.sleep(interval)

        self._cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info(f"缓存自动清理任务已启动，间隔: {interval}s")

    def stop_cleanup_task(self):
        """停止后台自动清理任务。

        取消正在运行的 asyncio 清理任务，重置 _cleanup_task 引用。
        在应用关闭时调用以确保资源正确释放。
        """
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None
            logger.info("缓存自动清理任务已停止")

    def clear_all(self):
        """清空所有缓存文件（保留目录结构）。

        递归遍历缓存目录，删除所有文件但保留子目录结构。
        使用 os.scandir 替代 os.walk 以获得更好的遍历性能。
        用于手动触发全量缓存清理或用户请求清空缓存。
        """
        if not os.path.exists(self.cache_dir):
            return

        self._clear_all_in_dir(self.cache_dir)
        logger.info("所有缓存文件已清空")

    def _clear_all_in_dir(self, dir_path: str) -> None:
        """递归删除指定目录下的所有文件（保留目录结构）。

        Args:
            dir_path: 要清空的目录路径。
        """
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        self._clear_all_in_dir(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            os.remove(entry.path)
                        except OSError:
                            continue
        except OSError:
            pass

    def get_cache_stats(self) -> dict:
        """获取缓存统计信息。

        使用 os.scandir 递归遍历，比 os.walk 更高效（DirEntry 缓存 stat 信息）。

        Returns:
            包含以下字段的字典:
            - total_files: 缓存文件总数
            - total_size_mb: 缓存总大小（MB）
            - cache_dir: 缓存目录路径
            - ttl_seconds: 文件 TTL（秒）
        """
        if not os.path.exists(self.cache_dir):
            return {"total_files": 0, "total_size_mb": 0}

        total_files = 0
        total_size = 0

        total_files, total_size = self._collect_stats_in_dir(self.cache_dir)

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": self.cache_dir,
            "ttl_seconds": self.ttl,
        }

    def _collect_stats_in_dir(self, dir_path: str) -> tuple[int, int]:
        """递归收集指定目录下的文件统计信息。

        Args:
            dir_path: 要扫描的目录路径。

        Returns:
            (文件总数, 文件总字节数) 元组。
        """
        total_files = 0
        total_size = 0
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        sub_files, sub_size = self._collect_stats_in_dir(entry.path)
                        total_files += sub_files
                        total_size += sub_size
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            total_files += 1
                            total_size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
        except OSError:
            pass
        return total_files, total_size


class LRUCache:
    """基于 LRU（最近最少使用）策略的固定容量线程安全内存缓存。

    使用 collections.OrderedDict 跟踪访问顺序，当缓存条目数超出 maxsize 时，
    自动淘汰最久未访问的条目（弹出 OrderedDict 首位元素）。

    所有公共方法均通过 threading.Lock 保证线程安全，支持多线程并发访问。
    同时提供命中/未命中统计，用于监控缓存效果。

    Attributes:
        _cache: 存储缓存键值对的 OrderedDict，键为 str，值为 Any。
        _maxsize: 缓存最大条目数，超出时自动淘汰。
        _hits: 缓存命中次数计数器。
        _misses: 缓存未命中次数计数器。
        _lock: 线程同步锁，保证并发安全。
    """

    def __init__(self, maxsize: int = 50) -> None:
        """初始化 LRU 缓存。

        Args:
            maxsize: 缓存最大条目数，默认 50。超出容量时自动淘汰最久未使用的条目。
        """
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """根据键获取缓存项，命中时移至末尾（最近使用位置）"""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        """插入或更新缓存项，超出容量时淘汰最久未使用的条目"""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        """检查键是否存在于缓存中（支持 ``key in cache`` 语法）。

        Args:
            key: 要检查的缓存键。

        Returns:
            键存在返回 True，否则返回 False。
        """
        with self._lock:
            return key in self._cache

    def __delitem__(self, key: str) -> None:
        """从缓存中删除指定键（支持 ``del cache[key]`` 语法）。

        如果键不存在则静默忽略，不抛出异常。

        Args:
            key: 要删除的缓存键。
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def get_stats(self) -> dict:
        """返回缓存性能统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 1),
                "size": len(self._cache),
                "maxsize": self._maxsize,
            }

    def reset_stats(self) -> None:
        """重置命中和未命中计数器"""
        with self._lock:
            self._hits = 0
            self._misses = 0


class AdaptiveLRUCache(LRUCache):
    """根据 GPU 显存使用率自适应调整容量的 LRU 缓存

    自动根据 GPU 显存利用率反向调整缓存大小：
    高 GPU 使用率触发缓存收缩以释放系统内存，低使用率允许缓存扩展。

    容量映射：
        GPU > 90% -> 5 条
        GPU > 75% -> 10 条
        GPU > 50% -> 15 条
        其他       -> 20 条

    Attributes:
        _CAPACITY_MAP: (gpu阈值, 缓存容量) 元组列表。
        _adapt_lock: 容量调整的线程锁。
    """

    _CAPACITY_MAP = [
        (90, 5),
        (75, 10),
        (50, 15),
        (0, 20),
    ]

    _MEMORY_LIMIT_MB = 512

    def __init__(self, default_maxsize: int = 15, adapt_interval: float = 30.0) -> None:
        """初始化自适应 LRU 缓存。

        Args:
            default_maxsize: 默认初始最大条目数，默认 15。
            adapt_interval: 容量自适应调整的最小间隔时间（秒），默认 30 秒。
                防止频繁查询 GPU 状态造成开销。
        """
        super().__init__(maxsize=default_maxsize)
        self._adapt_lock = threading.Lock()
        self._adapt_interval = adapt_interval
        self._last_adapt_time = 0.0
        self._put_count = 0
        self._adapt_every_n = 10
        self._total_memory_estimate = 0
        self._eviction_count = 0

    @staticmethod
    def _estimate_item_size(value: Any) -> int:
        """估算缓存值的内存占用（字节）

        Args:
            value: 需要估算的缓存值。

        Returns:
            估算的内存大小（字节）。
        """
        try:
            if isinstance(value, tuple) and len(value) > 0:
                first = value[0]
                if hasattr(first, "nbytes"):
                    total = first.nbytes
                    for item in value[1:]:
                        if hasattr(item, "nbytes"):
                            total += item.nbytes
                        else:
                            total += getattr(item, "__sizeof__", lambda: 1024)()
                    return total
            if hasattr(value, "__sizeof__"):
                return value.__sizeof__()
        except Exception:
            pass
        return 1024

    @staticmethod
    def _get_gpu_memory_percent() -> float:
        """通过 gpu_utils 获取当前 GPU 显存使用百分比

        Returns:
            显存使用百分比（0.0 ~ 100.0），GPU 不可用时返回 0.0。
        """
        try:
            from .gpu_utils import get_gpu_memory_info

            mem_info = get_gpu_memory_info()
            return mem_info.get("utilization_pct", 0.0)
        except Exception:
            return 0.0

    def _calculate_target_capacity(self) -> int:
        """根据当前 GPU 显存使用率计算目标缓存容量

        Returns:
            目标缓存容量（条目数）。
        """
        gpu_pct = self._get_gpu_memory_percent()
        for threshold, capacity in self._CAPACITY_MAP:
            if gpu_pct > threshold:
                return capacity
        return 20

    def adapt_capacity(self) -> int:
        """根据 GPU 显存使用率调整缓存容量并淘汰多余条目

        Returns:
            调整后的新缓存容量。
        """
        target = self._calculate_target_capacity()
        with self._adapt_lock:
            old_max = self._maxsize
            self._maxsize = target
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)
            if old_max != target:
                logger.info(
                    f"[AdaptiveCache] 容量调整: {old_max} -> {target} "
                    f"(GPU 使用率: {self._get_gpu_memory_percent():.1f}%)"
                )
        return target

    def put(self, key: str, value: Any) -> None:
        """插入或更新缓存项，同时跟踪内存估算并触发自适应调整"""
        size = self._estimate_item_size(value)
        with self._adapt_lock:
            if key in self._cache:
                old_value = self._cache[key]
                self._total_memory_estimate -= self._estimate_item_size(old_value)
            self._total_memory_estimate += size
        super().put(key, value)
        with self._adapt_lock:
            memory_limit = self._MEMORY_LIMIT_MB * 1024 * 1024
            while self._total_memory_estimate > memory_limit and len(self._cache) > 0:
                evicted_key, evicted_value = self._cache.popitem(last=False)
                evicted_size = self._estimate_item_size(evicted_value)
                self._total_memory_estimate -= evicted_size
                self._eviction_count += 1
        self._put_count += 1
        now = time.monotonic()
        if (
            len(self._cache) >= self._maxsize
            or now - self._last_adapt_time >= self._adapt_interval
            or self._put_count >= self._adapt_every_n
        ):
            self.adapt_capacity()
            self._last_adapt_time = now
            self._put_count = 0

    def __delitem__(self, key: str) -> None:
        """从缓存中删除指定键，同时更新内存估算。

        重写父类方法，在删除前减去被删除条目的估算内存占用。

        Args:
            key: 要删除的缓存键。
        """
        with self._adapt_lock:
            if key in self._cache:
                self._total_memory_estimate -= self._estimate_item_size(self._cache[key])
        super().__delitem__(key)

    def clear(self) -> None:
        """清空所有缓存项并重置统计信息"""
        with self._adapt_lock:
            self._cache.clear()
            self._total_memory_estimate = 0
            self._eviction_count = 0
        self.reset_stats()

    def get_stats(self) -> dict:
        """返回包含内存跟踪的缓存性能统计信息

        Returns:
            包含 hits、misses、hit_rate、size、maxsize、
            memory_estimate_mb、eviction_count、avg_item_size_kb 的字典。
        """
        with self._adapt_lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            memory_mb = self._total_memory_estimate / (1024 * 1024)
            cache_size = len(self._cache)
            avg_kb = (self._total_memory_estimate / cache_size / 1024) if cache_size > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 1),
                "size": cache_size,
                "maxsize": self._maxsize,
                "memory_estimate_mb": round(memory_mb, 2),
                "eviction_count": self._eviction_count,
                "avg_item_size_kb": round(avg_kb, 2),
            }
