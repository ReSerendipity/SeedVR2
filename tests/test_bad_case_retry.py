"""bad_case_retry.py 单元测试。

验证失败分类、参数调整、重试逻辑的纯函数行为，
不依赖 GPU/Engine 实例。
"""

from __future__ import annotations

import dataclasses
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrated_app.bad_case_retry import (
    FailureType,
    RetryConfig,
    adjust_params_for_retry,
    classify_failure,
    retry_with_bad_case_detection,
)

# 抑制测试中的日志噪音
logging.getLogger("app.integrated_app.bad_case_retry").setLevel(logging.CRITICAL)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """将退避等待替换为空操作，加速测试。"""

    async def _noop(_delay):
        return None

    monkeypatch.setattr("app.integrated_app.bad_case_retry.asyncio.sleep", _noop)


# ---------------------------------------------------------------------------
# 测试用 dataclass（模拟 ImageInferenceConfig）
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FakeConfig:
    blocks_to_swap: int = 32
    resolution: int = 2160
    seed: int = -1
    dit_model: str = "3b_fp16"
    max_resolution: int = 0


# ---------------------------------------------------------------------------
# classify_failure
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_oom_cuda_out_of_memory(self):
        has_failure, ftype, _reason = classify_failure(message="CUDA out of memory")
        assert has_failure
        assert ftype == FailureType.OOM

    def test_oom_runtime_error_cuda(self):
        has_failure, ftype, _reason = classify_failure(
            error=RuntimeError("RuntimeError: CUDA error: out of memory")
        )
        assert has_failure
        assert ftype == FailureType.OOM

    def test_oom_from_exception_type_name(self):
        has_failure, ftype, _reason = classify_failure(error=MemoryError("alloc failed"))
        assert has_failure
        assert ftype == FailureType.OOM

    def test_network_connection_timeout(self):
        has_failure, ftype, _reason = classify_failure(message="Connection timed out")
        assert has_failure
        assert ftype == FailureType.NETWORK

    def test_network_socket_error(self):
        has_failure, ftype, _reason = classify_failure(
            error=ConnectionError("socket error: broken pipe")
        )
        assert has_failure
        assert ftype == FailureType.NETWORK

    def test_cancelled_by_user(self):
        has_failure, ftype, _reason = classify_failure(message="InferenceCancelledError")
        assert not has_failure
        assert ftype == FailureType.CANCELLED

    def test_unknown_error(self):
        has_failure, ftype, _reason = classify_failure(message="Something went wrong")
        assert has_failure
        assert ftype == FailureType.UNKNOWN

    def test_empty_message(self):
        has_failure, ftype, _reason = classify_failure(message="")
        assert has_failure
        assert ftype == FailureType.UNKNOWN


# ---------------------------------------------------------------------------
# adjust_params_for_retry
# ---------------------------------------------------------------------------


class TestAdjustParams:
    cfg = RetryConfig()

    def test_oom_first_attempt_increases_blocks_to_swap(self):
        params = {"config": _FakeConfig(blocks_to_swap=32)}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 1, self.cfg)
        cfg = adjusted["config"]
        assert cfg.blocks_to_swap == 36  # 32 + 4

    def test_oom_second_attempt_reduces_resolution(self):
        params = {"config": _FakeConfig(blocks_to_swap=32, resolution=2160)}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 2, self.cfg)
        cfg = adjusted["config"]
        assert cfg.blocks_to_swap == 36
        assert cfg.resolution == 1620  # 2160 * 0.75 = 1620

    def test_oom_third_attempt_falls_back_precision(self):
        params = {"config": _FakeConfig(blocks_to_swap=32, resolution=2160, dit_model="3b_fp16")}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 3, self.cfg)
        cfg = adjusted["config"]
        assert cfg.blocks_to_swap == 36
        assert cfg.resolution == 1620
        assert cfg.dit_model == "3b_fp8"

    def test_oom_without_config_uses_top_level(self):
        params = {"blocks_to_swap": 32, "resolution": 2048}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 2, self.cfg)
        assert adjusted["blocks_to_swap"] == 36
        assert adjusted["resolution"] == 1536

    def test_network_does_not_degrade_params(self):
        params = {"config": _FakeConfig(blocks_to_swap=32, resolution=2160)}
        adjusted = adjust_params_for_retry(params, FailureType.NETWORK, 2, self.cfg)
        cfg = adjusted["config"]
        assert cfg.blocks_to_swap == 32  # 不变
        assert cfg.resolution == 2160  # 不变

    def test_seed_rotation(self):
        params = {"config": _FakeConfig(seed=42)}
        adjusted = adjust_params_for_retry(params, FailureType.NETWORK, 1, self.cfg)
        assert adjusted["config"].seed != 42

    def test_seed_rotation_random_when_minus_one(self):
        params = {"config": _FakeConfig(seed=-1)}
        adjusted = adjust_params_for_retry(params, FailureType.NETWORK, 1, self.cfg)
        assert adjusted["config"].seed >= 0  # 换成了随机正数

    def test_blocks_to_swap_capped(self):
        params = {"config": _FakeConfig(blocks_to_swap=35)}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 1, self.cfg)
        assert adjusted["config"].blocks_to_swap == 36  # capped at max

    def test_unknown_does_not_degrade(self):
        params = {"config": _FakeConfig(blocks_to_swap=32, resolution=2160)}
        adjusted = adjust_params_for_retry(params, FailureType.UNKNOWN, 2, self.cfg)
        assert adjusted["config"].blocks_to_swap == 32
        assert adjusted["config"].resolution == 2160

    def test_degradation_disabled_when_config_false(self):
        cfg = RetryConfig(enable_degradation=False)
        params = {"config": _FakeConfig(blocks_to_swap=32, resolution=2160)}
        adjusted = adjust_params_for_retry(params, FailureType.OOM, 2, cfg)
        assert adjusted["config"].blocks_to_swap == 32
        assert adjusted["config"].resolution == 2160


# ---------------------------------------------------------------------------
# retry_with_bad_case_detection（异步）
# ---------------------------------------------------------------------------


class TestRetryLoop:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        mock_result = MagicMock(success=True)
        mock_fn = AsyncMock(return_value=mock_result)
        result = await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert result.success is True
        assert result.attempts == 1
        assert result.degraded is False
        mock_fn.assert_called_once_with(x=1)

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        mock_fn = AsyncMock()
        mock_fn.side_effect = [
            MagicMock(success=False, error="CUDA out of memory"),
            MagicMock(success=True),
        ]
        result = await retry_with_bad_case_detection(mock_fn, {"config": _FakeConfig()})
        assert result.success
        assert result.attempts == 2
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_retries_on_exception_then_succeeds(self):
        mock_fn = AsyncMock()
        mock_fn.side_effect = [
            RuntimeError("CUDA out of memory: no available memory"),
            MagicMock(success=True),
        ]
        result = await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert result.success
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_graceful_degradation_when_retries_exhausted(self):
        mock_fn = AsyncMock(return_value=MagicMock(success=False, error="CUDA OOM"))
        result = await retry_with_bad_case_detection(
            mock_fn, {"x": 1}, RetryConfig(max_retries=2)
        )
        assert result.success is True  # 优雅降级
        assert result.attempts == 3
        assert result.degraded is True
        assert "重试耗尽" in result.failure_reason

    @pytest.mark.asyncio
    async def test_all_attempts_exception_returns_failure(self):
        mock_fn = AsyncMock(side_effect=RuntimeError("Something fatal"))
        result = await retry_with_bad_case_detection(
            mock_fn, {"x": 1}, RetryConfig(max_retries=2)
        )
        assert result.success is False
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_cancelled_error(self):
        mock_fn = AsyncMock(return_value=MagicMock(success=False, error="InferenceCancelledError"))
        result = await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert result.success is False
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_cancelled_exception_propagates_without_retry(self):
        mock_fn = AsyncMock(side_effect=RuntimeError("task cancelled by user"))
        with pytest.raises(RuntimeError):
            await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert mock_fn.await_count == 1  # 未重试

    @pytest.mark.asyncio
    async def test_network_error_retries_without_degradation(self):
        mock_fn = AsyncMock()
        mock_fn.side_effect = [
            MagicMock(success=False, error="Connection timed out"),
            MagicMock(success=True),
        ]
        result = await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert result.success
        assert result.attempts == 2
        assert result.degraded is False  # 网络错误不降级

    @pytest.mark.asyncio
    async def test_result_without_success_attr_treated_as_success(self):
        mock_fn = AsyncMock(return_value={"data": "ok"})
        result = await retry_with_bad_case_detection(mock_fn, {"x": 1})
        assert result.success is True
        assert result.result == {"data": "ok"}


if __name__ == "__main__":
    pytest.main([__file__, "-q", "-p", "no:cacheprovider"])