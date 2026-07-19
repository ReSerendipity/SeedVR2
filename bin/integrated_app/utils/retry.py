"""重试工具 - 指数退避 + 抖动

OPTIMIZE: 替代 unified.py 中固定 sleep 1/2 秒的重试逻辑，
         避免雪崩与连续故障期间的负载堆积。
"""
import asyncio
import random


async def exponential_backoff_with_jitter(
    attempt: int,
    base: float = 1.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.1,
) -> None:
    """指数退避 + 抖动等待

    Args:
        attempt: 当前重试次数（从 0 开始）
        base: 基础延迟秒数
        max_delay: 最大延迟秒数
        jitter_ratio: 抖动比例（0-1），基于计算后的延迟附加随机抖动
    """
    delay = min(base * (2 ** attempt), max_delay)
    if jitter_ratio > 0:
        delay += random.uniform(0, jitter_ratio * delay)
    await asyncio.sleep(delay)
