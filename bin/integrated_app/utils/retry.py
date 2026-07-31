"""异步重试工具 - 指数退避 + 随机抖动。

提供带抖动的指数退避等待函数，用于失败重试场景，避免固定间隔重试
导致的"雪崩效应"（thundering herd）和连续故障期间的负载堆积。

设计模式:
    - 指数退避 (Exponential Backoff)：每次重试延迟翻倍，快速降低重试频率
    - 抖动 (Jitter)：在计算延迟上附加随机偏移，避免多个客户端同时重试
    - 上限控制：设置最大延迟上限，防止无限期等待

性能优化点:
    - 替代原 unified.py 中固定 sleep 1/2 秒的简单重试逻辑
    - 抖动比例可配置，平衡公平性和重试及时性
    - 使用 asyncio.sleep 非阻塞等待，不阻塞事件循环

典型使用场景:
    - 文件 I/O 临时失败重试
    - 模型加载锁竞争等待
    - 外部资源暂时不可用的退避重试
"""
import asyncio
import random


async def exponential_backoff_with_jitter(
    attempt: int,
    base: float = 1.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.1,
) -> None:
    """异步等待，使用指数退避 + 随机抖动策略。

    延迟计算公式：
        delay = min(base * 2^attempt, max_delay)
        delay += random.uniform(0, jitter_ratio * delay)

    重试次数与延迟示例（base=1.0, max_delay=30.0, 无抖动）：
        attempt=0 → 1s
        attempt=1 → 2s
        attempt=2 → 4s
        attempt=3 → 8s
        attempt=4 → 16s
        attempt=5 → 30s (达到上限)

    Args:
        attempt: 当前重试次数（从 0 开始计数，0 表示第一次重试）
        base: 基础延迟秒数，默认 1.0 秒
        max_delay: 最大延迟秒数上限，默认 30.0 秒，防止无限增长
        jitter_ratio: 抖动比例（范围 0-1），默认 0.1 表示最多附加 10% 随机延迟；
            设为 0 则禁用抖动（不推荐，可能导致雪崩）

    Returns:
        None: 协程无返回值，等待指定时间后返回
    """
    delay = min(base * (2 ** attempt), max_delay)
    if jitter_ratio > 0:
        delay += random.uniform(0, jitter_ratio * delay)
    await asyncio.sleep(delay)
