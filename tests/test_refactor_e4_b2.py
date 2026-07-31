#!/usr/bin/env python3
"""SeedVR2 - 重构测试

覆盖本次重构的核心改动:
1. InferenceCancelledError 异常属性 (提案 2B)
2. TaskStateStoreProxy 浅拷贝语义 - 顶层字段修改不影响缓存 (提案 2A)
3. TaskStateStoreProxy.update 方法写回缓存 (提案 2A)
4. TaskStateStore.update_cached / get_cached_or_create (提案 2A)
5. TaskQueue on_cancel 回调在超时时被调用 (提案 2B)
6. TaskQueue request_cancel 调用 on_cancel (提案 2B)
7. SeedVR2Engine.request_cancel / _check_cancelled / _reset_cancel_token (提案 2B)

设计原则:
- 不依赖真实模型加载，使用 mock 或最小化夹具
- 遵循 AAA (Arrange-Act-Assert) 模式
- 测试名称表达意图
"""
import asyncio
import threading
import time

import pytest

from bin.integrated_app.exceptions import InferenceCancelledError, RestoreError


# ---------------------------------------------------------------------------
# 1. InferenceCancelledError 异常属性 (提案 2B)
# ---------------------------------------------------------------------------

class TestInferenceCancelledError:
    """验证推理取消异常的属性与继承关系"""

    def test_is_subclass_of_restore_error(self):
        """InferenceCancelledError 应继承 RestoreError，便于统一错误处理"""
        assert issubclass(InferenceCancelledError, RestoreError)

    def test_default_message(self):
        """默认消息应为'推理已被取消'"""
        err = InferenceCancelledError()
        assert err.message == "推理已被取消"
        assert "推理已被取消" in str(err)

    def test_custom_message(self):
        """支持自定义消息"""
        err = InferenceCancelledError("视频推理在阶段2被取消")
        assert err.message == "视频推理在阶段2被取消"

    def test_code_attribute(self):
        """错误码应为 INFERENCE_CANCELLED"""
        assert InferenceCancelledError.code == "INFERENCE_CANCELLED"
        err = InferenceCancelledError()
        assert err.code == "INFERENCE_CANCELLED"

    def test_custom_detail(self):
        """支持结构化 detail 字典"""
        err = InferenceCancelledError(detail={"stage": "image:stage2-dit-sample", "task_id": "abc123"})
        assert err.detail["stage"] == "image:stage2-dit-sample"
        assert err.detail["task_id"] == "abc123"

    def test_http_status_is_400(self):
        """HTTP 状态码应为 400（兼容标准 HTTP 状态码）"""
        assert InferenceCancelledError.http_status() == 400

    def test_to_dict_contains_code_and_message(self):
        """to_dict 应包含 code 和 message"""
        err = InferenceCancelledError("测试取消", detail={"stage": "stage1"})
        d = err.to_dict()
        assert d["code"] == "INFERENCE_CANCELLED"
        assert d["message"] == "测试取消"
        assert d["detail"]["stage"] == "stage1"

    def test_can_be_caught_as_restore_error(self):
        """应能被 except RestoreError 捕获"""
        with pytest.raises(RestoreError):
            raise InferenceCancelledError()


# ---------------------------------------------------------------------------
# 2. TaskStateStoreProxy 浅拷贝语义 (提案 2A)
# ---------------------------------------------------------------------------

from bin.integrated_app.services.task_state import TaskStateStore, task_state_store
from bin.integrated_app.routes.restore.common import TaskStateStoreProxy


@pytest.fixture
def clean_store():
    """每个测试使用独立的 TaskStateStore，避免全局单例污染"""
    store = TaskStateStore(max_cache_size=100)
    # 预填充一个任务
    store._cache["task-1"] = {
        "task_id": "task-1",
        "status": "pending",
        "progress": 0.0,
        "results": [{"path": "a.png", "status": "pending"}],
        "current_index": -1,
    }
    return store


class TestTaskStateStoreProxyShallowCopy:
    """验证 TaskStateStoreProxy 的浅拷贝语义"""

    def test_getitem_returns_copy_not_reference(self, clean_store):
        """__getitem__ 返回浅拷贝，修改顶层字段不影响缓存"""
        proxy = TaskStateStoreProxy(clean_store)
        cached = proxy["task-1"]
        cached["status"] = "completed"
        cached["progress"] = 100.0

        # 缓存内部状态不应被影响
        assert clean_store._cache["task-1"]["status"] == "pending"
        assert clean_store._cache["task-1"]["progress"] == 0.0

    def test_get_returns_copy_not_reference(self, clean_store):
        """get() 返回浅拷贝，修改顶层字段不影响缓存"""
        proxy = TaskStateStoreProxy(clean_store)
        cached = proxy.get("task-1")
        assert cached is not None
        cached["current_index"] = 5

        assert clean_store._cache["task-1"]["current_index"] == -1

    def test_nested_list_is_shared_reference(self, clean_store):
        """浅拷贝下嵌套 list 仍为引用共享，修改元素影响缓存"""
        proxy = TaskStateStoreProxy(clean_store)
        cached = proxy.get("task-1")
        cached["results"][0]["status"] = "completed"

        # 嵌套 dict 修改应影响缓存（浅拷贝特性）
        assert clean_store._cache["task-1"]["results"][0]["status"] == "completed"

    def test_update_writes_back_to_cache(self, clean_store):
        """update() 方法应将顶层字段写回缓存"""
        proxy = TaskStateStoreProxy(clean_store)
        proxy.update("task-1", status="processing", progress=50.0, current_index=3)

        cached = clean_store._cache["task-1"]
        assert cached["status"] == "processing"
        assert cached["progress"] == 50.0
        assert cached["current_index"] == 3

    def test_setitem_writes_back_to_cache(self, clean_store):
        """__setitem__ 应通过 update_cached 写回缓存"""
        proxy = TaskStateStoreProxy(clean_store)
        proxy["task-1"] = {"status": "completed", "progress": 100.0}

        cached = clean_store._cache["task-1"]
        assert cached["status"] == "completed"
        assert cached["progress"] == 100.0

    def test_getitem_raises_keyerror_for_missing(self, clean_store):
        """__getitem__ 对不存在的 task_id 抛出 KeyError"""
        proxy = TaskStateStoreProxy(clean_store)
        with pytest.raises(KeyError):
            _ = proxy["nonexistent"]

    def test_get_returns_default_for_missing(self, clean_store):
        """get() 对不存在的 task_id 返回 default"""
        proxy = TaskStateStoreProxy(clean_store)
        assert proxy.get("nonexistent") is None
        assert proxy.get("nonexistent", {}) == {}

    def test_contains(self, clean_store):
        """__contains__ 正确判断存在性"""
        proxy = TaskStateStoreProxy(clean_store)
        assert "task-1" in proxy
        assert "nonexistent" not in proxy


# ---------------------------------------------------------------------------
# 3. TaskStateStore.update_cached / get_cached_or_create (提案 2A)
# ---------------------------------------------------------------------------

class TestTaskStateStoreCachedMethods:
    """验证 TaskStateStore 的缓存操作方法"""

    def test_update_cached_writes_fields(self, clean_store):
        """update_cached 应写入字段并返回拷贝"""
        result = clean_store.update_cached("task-1", status="running", progress=25.5)
        assert result is not None
        assert result["status"] == "running"
        assert result["progress"] == 25.5
        # 缓存内部也应更新
        assert clean_store._cache["task-1"]["status"] == "running"

    def test_update_cached_returns_none_for_missing(self, clean_store):
        """update_cached 对不存在的 task_id 返回 None"""
        result = clean_store.update_cached("nonexistent", status="running")
        assert result is None

    def test_get_cached_returns_copy(self, clean_store):
        """get_cached 返回拷贝，修改不影响缓存"""
        cached = clean_store.get_cached("task-1")
        assert cached is not None
        cached["status"] = "modified"
        assert clean_store._cache["task-1"]["status"] == "pending"

    def test_get_cached_returns_none_for_missing(self, clean_store):
        """get_cached 对不存在的 task_id 返回 None"""
        assert clean_store.get_cached("nonexistent") is None

    def test_get_cached_or_create_creates_new(self, clean_store):
        """get_cached_or_create 对不存在的 task_id 用 template 创建"""
        template = {
            "task_id": "new-task",
            "type": "batch",
            "total": 5,
            "results": [],
        }
        result = clean_store.get_cached_or_create("new-task", template=template)
        assert result["task_id"] == "new-task"
        assert result["type"] == "batch"
        # 应写入缓存
        assert "new-task" in clean_store._cache

    def test_get_cached_or_create_returns_existing(self, clean_store):
        """get_cached_or_create 对已存在的 task_id 返回缓存拷贝"""
        result = clean_store.get_cached_or_create("task-1", template={"task_id": "ignored"})
        assert result["task_id"] == "task-1"
        assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# 4. TaskQueue on_cancel 回调机制 (提案 2B)
# ---------------------------------------------------------------------------

from bin.integrated_app.task_queue import TaskQueue


@pytest.fixture
def short_timeout_queue():
    """超时时间为 0.1 秒的队列，便于测试超时"""
    return TaskQueue(maxsize=10, task_timeout_seconds=1)


class TestTaskQueueOnCancel:
    """验证 TaskQueue 的 on_cancel 回调机制"""

    @pytest.mark.asyncio
    async def test_timeout_invokes_on_cancel(self, short_timeout_queue):
        """任务超时时应调用 on_cancel 回调"""
        cancel_called = threading.Event()

        def on_cancel():
            cancel_called.set()

        async def slow_task():
            await asyncio.sleep(10)  # 远超超时时间

        await short_timeout_queue.start()
        try:
            await short_timeout_queue.submit("timeout-task", slow_task, on_cancel=on_cancel)
            # 等待超时触发（超时 1s + 容差）
            await asyncio.sleep(2.5)
            assert cancel_called.is_set(), "on_cancel 回调应在超时后被调用"
        finally:
            await short_timeout_queue.stop()

    @pytest.mark.asyncio
    async def test_request_cancel_invokes_on_cancel(self, short_timeout_queue):
        """主动取消任务时应调用 on_cancel 回调"""
        cancel_called = threading.Event()

        def on_cancel():
            cancel_called.set()

        started = asyncio.Event()

        async def long_task():
            started.set()
            await asyncio.sleep(10)

        await short_timeout_queue.start()
        try:
            await short_timeout_queue.submit("cancel-task", long_task, on_cancel=on_cancel)
            await asyncio.sleep(0.3)  # 等待任务开始
            short_timeout_queue.request_cancel("cancel-task")
            await asyncio.sleep(0.5)
            assert cancel_called.is_set(), "on_cancel 回调应在 request_cancel 后被调用"
        finally:
            await short_timeout_queue.stop()

    @pytest.mark.asyncio
    async def test_submit_without_on_cancel_still_works(self, short_timeout_queue):
        """不注入 on_cancel 时队列仍正常工作（向后兼容）"""
        completed = asyncio.Event()

        async def quick_task():
            completed.set()

        await short_timeout_queue.start()
        try:
            await short_timeout_queue.submit("no-callback-task", quick_task, on_cancel=None)
            await asyncio.sleep(0.5)
            assert completed.is_set(), "任务应正常完成"
        finally:
            await short_timeout_queue.stop()

    @pytest.mark.asyncio
    async def test_on_cancel_exception_does_not_crash_worker(self, short_timeout_queue):
        """on_cancel 回调抛异常不应导致 worker 崩溃"""
        def bad_cancel():
            raise RuntimeError("on_cancel 内部错误")

        async def slow_task():
            await asyncio.sleep(10)

        await short_timeout_queue.start()
        try:
            await short_timeout_queue.submit("bad-callback-task", slow_task, on_cancel=bad_cancel)
            await asyncio.sleep(2.5)
            # worker 应仍能处理后续任务
            completed = asyncio.Event()

            async def quick_task():
                completed.set()

            await short_timeout_queue.submit("after-bad", quick_task)
            await asyncio.sleep(0.5)
            assert completed.is_set(), "worker 应在 on_cancel 异常后仍能继续工作"
        finally:
            await short_timeout_queue.stop()


# ---------------------------------------------------------------------------
# 5. SeedVR2Engine CancellationToken 机制 (提案 2B)
# ---------------------------------------------------------------------------

class TestSeedVR2EngineCancellationToken:
    """验证 SeedVR2Engine 的 CancellationToken 机制

    使用最小化 mock，不加载真实模型。
    """

    def _make_engine(self):
        """构造一个最小化的 SeedVR2Engine 实例（不加载模型）"""
        from bin.integrated_app.engines.seedvr2_engine import SeedVR2Engine
        engine = SeedVR2Engine.__new__(SeedVR2Engine)
        engine.config = {}
        engine._cancel_event = threading.Event()
        return engine

    def test_request_cancel_sets_event(self):
        """request_cancel 应设置 _cancel_event"""
        engine = self._make_engine()
        assert not engine._cancel_event.is_set()
        engine.request_cancel()
        assert engine._cancel_event.is_set()

    def test_reset_cancel_token_clears_event(self):
        """_reset_cancel_token 应清除 _cancel_event"""
        engine = self._make_engine()
        engine._cancel_event.set()
        engine._reset_cancel_token()
        assert not engine._cancel_event.is_set()

    def test_check_cancelled_raises_when_set(self):
        """_cancel_event 设置后，_check_cancelled 应抛出 InferenceCancelledError"""
        engine = self._make_engine()
        engine._cancel_event.set()
        with pytest.raises(InferenceCancelledError) as exc_info:
            engine._check_cancelled("image:stage2-dit-sample")
        assert "image:stage2-dit-sample" in str(exc_info.value)
        assert exc_info.value.detail["stage"] == "image:stage2-dit-sample"

    def test_check_cancelled_noop_when_not_set(self):
        """_cancel_event 未设置时，_check_cancelled 不应抛出异常"""
        engine = self._make_engine()
        # 不应抛出异常
        engine._check_cancelled("image:stage1-vae-encode")

    def test_reset_then_check_does_not_raise(self):
        """reset 后 _check_cancelled 不应抛出异常"""
        engine = self._make_engine()
        engine._cancel_event.set()
        engine._reset_cancel_token()
        engine._check_cancelled("video:stage3-vae-decode")


# ---------------------------------------------------------------------------
# 6. PathGuard 白名单守卫 (提案 1) - 补充验证
# ---------------------------------------------------------------------------

from bin.integrated_app.security.path_guard import build_default_path_guard


class TestPathGuardWhitelist:
    """验证 PathGuard 白名单机制替代原黑名单"""

    def test_build_default_path_guard_returns_guard(self, tmp_path):
        """build_default_path_guard 应返回有效的 PathGuard"""
        guard = build_default_path_guard(str(tmp_path), [])
        assert guard is not None

    def test_safe_path_inside_allowed(self, tmp_path):
        """允许目录内的路径应通过安全检查"""
        # build_default_path_guard 默认允许 {root}/outputs 和 {root}/data/uploads
        # 通过 extra_dirs 传入 tmp_path 使其成为允许目录
        guard = build_default_path_guard(str(tmp_path), [str(tmp_path)])
        safe_file = tmp_path / "subdir" / "file.png"
        safe_file.parent.mkdir(parents=True)
        safe_file.touch()
        assert guard.is_safe_path(str(safe_file)) is True

    def test_unsafe_path_outside_allowed(self, tmp_path):
        """允许目录外的路径不应通过安全检查"""
        guard = build_default_path_guard(str(tmp_path), [str(tmp_path)])
        # tmp_path 的父目录不在白名单内
        outside = tmp_path.parent
        assert guard.is_safe_path(str(outside)) is False

    def test_path_traversal_blocked(self, tmp_path):
        """路径遍历（..）应被阻止"""
        guard = build_default_path_guard(str(tmp_path), [str(tmp_path)])
        traversal = str(tmp_path / ".." / ".." / "etc" / "passwd")
        assert guard.is_safe_path(traversal) is False


# ---------------------------------------------------------------------------
# 7. 显式参数化 _load_dit_model / _load_vae_model (提案 3) - 签名验证
# ---------------------------------------------------------------------------

import inspect


class TestExplicitParameterization:
    """验证 _load_dit_model / _load_vae_model 的显式参数签名"""

    def _make_engine(self):
        from bin.integrated_app.engines.seedvr2_engine import SeedVR2Engine
        engine = SeedVR2Engine.__new__(SeedVR2Engine)
        engine.config = {}
        return engine

    def test_load_dit_model_accepts_explicit_params(self):
        """_load_dit_model 应接受 blocks_to_swap/swap_io_components/offload_device/attention_mode"""
        sig = inspect.signature(self._make_engine()._load_dit_model)
        params = sig.parameters
        assert "blocks_to_swap" in params
        assert "swap_io_components" in params
        assert "offload_device" in params
        assert "attention_mode" in params
        # 这些参数应有默认值 None（向后兼容）
        assert params["blocks_to_swap"].default is None
        assert params["swap_io_components"].default is None
        assert params["offload_device"].default is None
        assert params["attention_mode"].default is None

    def test_load_vae_model_accepts_vae_tiled_config(self):
        """_load_vae_model 应接受 vae_tiled_config 参数"""
        sig = inspect.signature(self._make_engine()._load_vae_model)
        params = sig.parameters
        assert "vae_tiled_config" in params
        assert params["vae_tiled_config"].default is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
