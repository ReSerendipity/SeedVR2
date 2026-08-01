"""FileCache / LRUCache / AdaptiveLRUCache 单元测试

覆盖缓存模块的文件操作、TTL 清理、LRU 淘汰和自适应容量调整。
使用 tmp_path 隔离文件系统，mock GPU 显存查询。
"""

import os
import time
from unittest.mock import patch

from bin.integrated_app.cache import AdaptiveLRUCache, FileCache, LRUCache

# ---------------------------------------------------------------------------
# FileCache
# ---------------------------------------------------------------------------


class TestFileCache:
    """FileCache 文件缓存管理器测试"""

    def test_generate_unique_filename_preserves_extension(self, tmp_path):
        cache = FileCache(str(tmp_path))
        name = cache.generate_unique_filename("photo.png")
        assert name.endswith(".png")

    def test_generate_unique_filename_no_extension(self, tmp_path):
        cache = FileCache(str(tmp_path))
        name = cache.generate_unique_filename("README")
        assert name.endswith(".bin")

    def test_generate_unique_filename_is_unique(self, tmp_path):
        cache = FileCache(str(tmp_path))
        names = {cache.generate_unique_filename("a.png") for _ in range(20)}
        assert len(names) == 20

    def test_get_cache_path(self, tmp_path):
        cache = FileCache(str(tmp_path))
        path = cache.get_cache_path("file.txt")
        assert path == os.path.join(str(tmp_path), "file.txt")

    def test_save_bytes(self, tmp_path):
        cache = FileCache(str(tmp_path))
        data = b"hello world"
        name, path = cache.save_bytes(data, "test.jpg")
        assert os.path.exists(path)
        with open(path, "rb") as f:
            assert f.read() == data
        assert name.endswith(".jpg")

    def test_save_bytes_with_subdir(self, tmp_path):
        cache = FileCache(str(tmp_path))
        name, path = cache.save_bytes(b"data", "f.bin", sub_dir="sub")
        assert os.path.exists(path)
        assert "sub" in path

    def test_file_exists(self, tmp_path):
        cache = FileCache(str(tmp_path))
        cache.save_bytes(b"x", "a.txt")
        name = os.listdir(str(tmp_path))[0]
        assert cache.file_exists(name)
        assert not cache.file_exists("nonexistent")

    def test_get_file_path(self, tmp_path):
        cache = FileCache(str(tmp_path))
        name, _ = cache.save_bytes(b"x", "a.txt")
        path = cache.get_file_path(name)
        assert path is not None
        assert os.path.exists(path)

    def test_get_file_path_nonexistent(self, tmp_path):
        cache = FileCache(str(tmp_path))
        assert cache.get_file_path("nope") is None

    def test_delete_file(self, tmp_path):
        cache = FileCache(str(tmp_path))
        _, path = cache.save_bytes(b"x", "a.txt")
        assert cache.delete_file(path)
        assert not os.path.exists(path)

    def test_delete_nonexistent_file(self, tmp_path):
        cache = FileCache(str(tmp_path))
        assert not cache.delete_file(str(tmp_path / "nonexistent"))

    def test_cleanup_expired(self, tmp_path):
        cache = FileCache(str(tmp_path), ttl=1)
        cache.save_bytes(b"old", "a.txt")
        time.sleep(1.1)
        cleaned = cache.cleanup_expired()
        assert cleaned == 1

    def test_cleanup_no_expired(self, tmp_path):
        cache = FileCache(str(tmp_path), ttl=3600)
        cache.save_bytes(b"new", "a.txt")
        assert cache.cleanup_expired() == 0

    def test_clear_all(self, tmp_path):
        cache = FileCache(str(tmp_path))
        cache.save_bytes(b"a", "1.txt")
        cache.save_bytes(b"b", "2.txt")
        cache.clear_all()
        assert len(os.listdir(str(tmp_path))) == 0

    def test_get_cache_stats_empty(self, tmp_path):
        cache = FileCache(str(tmp_path))
        stats = cache.get_cache_stats()
        assert stats["total_files"] == 0
        assert stats["total_size_mb"] == 0

    def test_get_cache_stats_with_files(self, tmp_path):
        cache = FileCache(str(tmp_path))
        cache.save_bytes(b"data data data data", "a.txt")
        stats = cache.get_cache_stats()
        assert stats["total_files"] == 1
        assert "cache_dir" in stats
        assert "ttl_seconds" in stats

    def test_stop_cleanup_task_when_none(self, tmp_path):
        cache = FileCache(str(tmp_path))
        cache.stop_cleanup_task()  # should not raise


# ---------------------------------------------------------------------------
# LRUCache
# ---------------------------------------------------------------------------


class TestLRUCache:
    """LRUCache 内存缓存测试"""

    def test_get_miss(self):
        cache = LRUCache(maxsize=5)
        assert cache.get("missing") is None

    def test_get_hit(self):
        cache = LRUCache(maxsize=5)
        cache.put("key", "value")
        assert cache.get("key") == "value"

    def test_eviction_order(self):
        cache = LRUCache(maxsize=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)
        assert cache.get("a") is None
        assert cache.get("b") == 2

    def test_put_update_existing(self):
        cache = LRUCache(maxsize=3)
        cache.put("a", 1)
        cache.put("a", 2)
        assert cache.get("a") == 2

    def test_contains(self):
        cache = LRUCache(maxsize=5)
        cache.put("a", 1)
        assert "a" in cache
        assert "b" not in cache

    def test_delitem(self):
        cache = LRUCache(maxsize=5)
        cache.put("a", 1)
        del cache["a"]
        assert "a" not in cache

    def test_delitem_nonexistent(self):
        cache = LRUCache(maxsize=5)
        del cache["nonexistent"]  # should not raise

    def test_get_stats(self):
        cache = LRUCache(maxsize=5)
        cache.put("a", 1)
        cache.get("a")
        cache.get("miss")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["maxsize"] == 5

    def test_reset_stats(self):
        cache = LRUCache(maxsize=5)
        cache.put("a", 1)
        cache.get("a")
        cache.reset_stats()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_lru_order_on_get(self):
        cache = LRUCache(maxsize=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.get("a")  # a -> most recently used
        cache.put("d", 4)  # should evict b (LRU)
        assert cache.get("b") is None
        assert cache.get("a") == 1


# ---------------------------------------------------------------------------
# AdaptiveLRUCache
# ---------------------------------------------------------------------------


class TestAdaptiveLRUCache:
    """AdaptiveLRUCache GPU 感知自适应缓存测试"""

    def test_estimate_item_size_tensor(self):
        """估算含 tensor 的元组大小"""

        class FakeTensor:
            nbytes = 1024

        size = AdaptiveLRUCache._estimate_item_size((FakeTensor(),))
        assert size == 1024

    def test_estimate_item_size_plain(self):
        size = AdaptiveLRUCache._estimate_item_size("hello")
        assert size > 0

    def test_estimate_item_size_fallback(self):
        """无法估算时返回默认值"""
        size = AdaptiveLRUCache._estimate_item_size(None)
        assert size >= 0

    def test_capacity_map_thresholds(self):
        assert AdaptiveLRUCache._CAPACITY_MAP[0] == (90, 5)
        assert AdaptiveLRUCache._CAPACITY_MAP[-1] == (0, 20)

    def test_calculate_target_capacity_high_usage(self):
        """GPU > 90% 时容量收缩到 5"""
        cache = AdaptiveLRUCache(default_maxsize=15)
        with patch.object(AdaptiveLRUCache, "_get_gpu_memory_percent", return_value=95.0):
            target = cache._calculate_target_capacity()
        assert target == 5

    def test_calculate_target_capacity_low_usage(self):
        """GPU < 50% 时容量扩展到 20"""
        cache = AdaptiveLRUCache(default_maxsize=5)
        with patch.object(AdaptiveLRUCache, "_get_gpu_memory_percent", return_value=30.0):
            target = cache._calculate_target_capacity()
        assert target == 20

    def test_calculate_target_capacity_mid_usage(self):
        """GPU 50-75% 时容量为 15"""
        cache = AdaptiveLRUCache(default_maxsize=5)
        with patch.object(AdaptiveLRUCache, "_get_gpu_memory_percent", return_value=60.0):
            target = cache._calculate_target_capacity()
        assert target == 15
