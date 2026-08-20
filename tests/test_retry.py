"""测试指数退避 + 抖动重试工具

ROBUSTNESS: 覆盖退避计算、上限、抖动范围、attempt=0 行为，
           通过 mock asyncio.sleep 避免真实延迟。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.integrated_app.utils.retry import exponential_backoff_with_jitter


class TestExponentialBackoffCalculation:
    """退避时长计算（不实际 sleep）"""

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=0.0)
    async def test_attempt_0_uses_base_delay(self, mock_uniform, mock_sleep):
        await exponential_backoff_with_jitter(attempt=0, base=1.0)
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=0.0)
    async def test_exponential_growth(self, mock_uniform, mock_sleep):
        """delay = base * 2^attempt"""
        for attempt, expected in [(0, 1.0), (1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0)]:
            mock_sleep.reset_mock()
            await exponential_backoff_with_jitter(attempt=attempt, base=1.0)
            mock_sleep.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=0.0)
    async def test_max_delay_caps_growth(self, mock_uniform, mock_sleep):
        """delay 不超过 max_delay"""
        await exponential_backoff_with_jitter(attempt=20, base=1.0, max_delay=30.0)
        mock_sleep.assert_awaited_once_with(30.0)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=0.0)
    async def test_custom_base(self, mock_uniform, mock_sleep):
        await exponential_backoff_with_jitter(attempt=2, base=0.5)
        # 0.5 * 2^2 = 2.0
        mock_sleep.assert_awaited_once_with(2.0)


class TestJitter:
    """抖动行为"""

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=0.5)
    async def test_jitter_added_to_delay(self, mock_uniform, mock_sleep):
        """jitter_ratio > 0 时，附加 random.uniform(0, jitter_ratio * delay)"""
        # attempt=2, base=1.0 → delay=4.0; jitter=0.1*4.0=0.4; uniform 返回 0.5
        # 但 uniform 被 mock 为返回 0.5，最终 delay = 4.0 + 0.5 = 4.5
        await exponential_backoff_with_jitter(attempt=2, base=1.0, max_delay=100.0, jitter_ratio=0.1)
        mock_sleep.assert_awaited_once_with(4.5)
        # 验证 uniform 被调用时上限是 0.1 * 4.0 = 0.4
        mock_uniform.assert_called_once_with(0, 0.4)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform")
    async def test_zero_jitter_skips_random(self, mock_uniform, mock_sleep):
        """jitter_ratio=0 时不调用 random.uniform"""
        await exponential_backoff_with_jitter(attempt=0, jitter_ratio=0)
        mock_uniform.assert_not_called()
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.integrated_app.utils.retry.random.uniform", return_value=3.0)
    async def test_jitter_applied_after_max_cap(self, mock_uniform, mock_sleep):
        """抖动在 max_delay 截断后才附加"""
        # attempt=20, base=1.0, max_delay=30.0 → delay=30.0
        # jitter_ratio=0.1 → 附加 uniform(0, 3.0)，返回 3.0
        # 最终 = 33.0
        await exponential_backoff_with_jitter(attempt=20, base=1.0, max_delay=30.0, jitter_ratio=0.1)
        mock_sleep.assert_awaited_once_with(33.0)
        mock_uniform.assert_called_once_with(0, 3.0)


class TestIntegration:
    """集成行为：函数确实 await 了 sleep"""

    @pytest.mark.asyncio
    async def test_function_is_coroutine(self):
        import inspect

        assert inspect.iscoroutinefunction(exponential_backoff_with_jitter)

    @pytest.mark.asyncio
    @patch("app.integrated_app.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_call_returns_none(self, mock_sleep):
        result = await exponential_backoff_with_jitter(attempt=0)
        assert result is None
