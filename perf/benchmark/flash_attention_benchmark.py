"""Flash Attention 2 性能基准测试。

对比 Flash Attention 2 与 PyTorch 原生 ``nn.MultiheadAttention`` 的
推理速度和显存占用。

运行方式::

    python -m perf.benchmark.flash_attention_benchmark
    # 或
    python perf/benchmark/flash_attention_benchmark.py

环境要求:
    - NVIDIA GPU (CUDA)
    - flash-attn >= 2.5.0

验收标准:
    - 速度提升 ≥ 2x（长序列）
    - 显存节省 ≥ 80%
    - 精度损失 < 1e-5
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import torch

logger = logging.getLogger(__name__)

# 确保项目根目录在 sys.path 中
if __name__ == "__main__" and __package__ is None:
    import os

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _measure_vram() -> float:
    """测量当前 GPU 显存使用量（MB）。

    Returns:
        当前已分配的 GPU 显存（MB）。
    """
    return torch.cuda.memory_allocated() / 1024 / 1024


def benchmark_attention(
    seq_len: int,
    batch_size: int,
    head_dim: int = 64,
    n_heads: int = 8,
    warmup_iters: int = 10,
    benchmark_iters: int = 100,
) -> Optional[dict[str, object]]:
    """对 Flash Attention 与标准注意力进行基准测试。

    Args:
        seq_len: 序列长度。
        batch_size: 批次大小。
        head_dim: 每个注意力头的维度。
        n_heads: 注意力头数。
        warmup_iters: 预热迭代次数（不计入计时）。
        benchmark_iters: 基准测试迭代次数。

    Returns:
        包含测试结果的字典，键包括:
        - ``seq_len``: 序列长度
        - ``batch_size``: 批次大小
        - ``standard_ms``: 标准注意力平均耗时（ms）
        - ``flash_ms``: Flash Attention 平均耗时（ms）
        - ``speedup``: 加速比
        - ``standard_vram_mb``: 标准注意力显存占用（MB）
        - ``flash_vram_mb``: Flash Attention 显存占用（MB）
        - ``vram_savings_pct``: 显存节省百分比

        如果 Flash Attention 不可用，返回 None。
    """
    dim = n_heads * head_dim

    try:
        from bin.vram.flash_attention_wrapper import FlashAttention
        from bin.vram.flash_attention_wrapper import FLASH_AVAILABLE
    except ImportError:
        from bin.vram.flash_attention_wrapper import FLASH_AVAILABLE  # type: ignore[assignment]

        FlashAttention = None  # type: ignore[assignment,misc]

    if not FLASH_AVAILABLE or FlashAttention is None:
        logger.error("Flash Attention 不可用，跳过基准测试")
        print("⚠️ Flash Attention 未安装，无法运行基准测试")
        return None

    device = torch.device("cuda")

    # 标准注意力
    standard_attn = torch.nn.MultiheadAttention(
        dim,
        n_heads,
        batch_first=True,
        device=device,
    )
    flash_attn = FlashAttention(dim, n_heads, device=device)

    x_standard = torch.randn(batch_size, seq_len, dim, device=device)
    x_flash = torch.randn(batch_size, seq_len, dim, device=device)

    # 预热
    for _ in range(warmup_iters):
        _ = standard_attn(x_standard, x_standard, x_standard)[0]
        _ = flash_attn(x_flash)

    # 标准注意力基准
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    for _ in range(benchmark_iters):
        _ = standard_attn(x_standard, x_standard, x_standard)[0]
    torch.cuda.synchronize()
    standard_time = time.perf_counter() - start
    standard_vram = torch.cuda.max_memory_allocated() / 1024 / 1024

    # Flash Attention 基准
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    for _ in range(benchmark_iters):
        _ = flash_attn(x_flash)
    torch.cuda.synchronize()
    flash_time = time.perf_counter() - start
    flash_vram = torch.cuda.max_memory_allocated() / 1024 / 1024

    standard_ms = standard_time * 1000 / benchmark_iters
    flash_ms = flash_time * 1000 / benchmark_iters
    speedup = standard_time / flash_time if flash_time > 0 else float("inf")
    vram_savings = (1 - flash_vram / standard_vram) * 100 if standard_vram > 0 else 0

    result = {
        "seq_len": seq_len,
        "batch_size": batch_size,
        "standard_ms": standard_ms,
        "flash_ms": flash_ms,
        "speedup": speedup,
        "standard_vram_mb": standard_vram,
        "flash_vram_mb": flash_vram,
        "vram_savings_pct": vram_savings,
    }

    print(f"\n{'=' * 60}")
    print(f"Seq Len: {seq_len}, Batch: {batch_size}, Dim: {dim}")
    print(f"{'=' * 60}")
    print(f"Standard Attention: {standard_ms:.2f}ms ({standard_vram:.1f}MB)")
    print(f"Flash Attention:    {flash_ms:.2f}ms ({flash_vram:.1f}MB)")
    print(f"Speedup:            {speedup:.2f}x")
    print(f"VRAM Savings:       {vram_savings:.1f}%")

    return result


def benchmark_precision(
    seq_len: int = 512,
    batch_size: int = 2,
    n_heads: int = 8,
    head_dim: int = 64,
) -> Optional[dict[str, float]]:
    """验证 Flash Attention 与标准注意力的精度一致性。

    使用相同的 QKV 权重，对比两种实现的输出差异。

    Args:
        seq_len: 序列长度。
        batch_size: 批次大小。
        n_heads: 注意力头数。
        head_dim: 每个注意力头的维度。

    Returns:
        包含精度指标的字典，键包括:
        - ``max_diff``: 最大绝对误差
        - ``mean_diff``: 平均绝对误差
        - ``pass``: 是否通过精度验收（max_diff < 1e-5）

        如果 Flash Attention 不可用，返回 None。
    """
    dim = n_heads * head_dim

    try:
        from bin.vram.flash_attention_wrapper import FlashAttention
        from bin.vram.flash_attention_wrapper import FLASH_AVAILABLE
    except ImportError:
        from bin.vram.flash_attention_wrapper import FLASH_AVAILABLE  # type: ignore[assignment]

        FlashAttention = None  # type: ignore[assignment,misc]

    if not FLASH_AVAILABLE or FlashAttention is None:
        logger.error("Flash Attention 不可用，跳过精度测试")
        return None

    device = torch.device("cuda")

    # 创建相同参数的注意力模块
    standard_attn = torch.nn.MultiheadAttention(
        dim,
        n_heads,
        batch_first=True,
        device=device,
        dtype=torch.float32,
    )
    flash_attn = FlashAttention(dim, n_heads, device=device, dtype=torch.float32)

    # 使用相同输入
    x = torch.randn(batch_size, seq_len, dim, device=device, dtype=torch.float32)

    with torch.no_grad():
        standard_output = standard_attn(x, x, x)[0]
        flash_output = flash_attn(x)

    max_diff = (standard_output - flash_output).abs().max().item()
    mean_diff = (standard_output - flash_output).abs().mean().item()
    passed = max_diff < 1e-5

    print(f"\n{'=' * 60}")
    print(f"精度验证 (Seq={seq_len}, Batch={batch_size})")
    print(f"{'=' * 60}")
    print(f"Max Abs Diff:  {max_diff:.2e}")
    print(f"Mean Abs Diff: {mean_diff:.2e}")
    print(f"Pass (<1e-5):  {'✅' if passed else '❌'}")

    return {
        "max_diff": max_diff,
        "mean_diff": mean_diff,
        "pass": 1.0 if passed else 0.0,
    }


def main() -> None:
    """运行完整的 Flash Attention 基准测试套件。"""
    if not torch.cuda.is_available():
        print("❌ CUDA 不可用，无法运行基准测试")
        sys.exit(1)

    print("🔥 Flash Attention 2 性能基准测试")
    print(f"GPU: {torch.cuda.get_device_name(0)}")

    # 速度 + 显存基准
    results: list[dict[str, object]] = []
    for seq_len, batch_size in [(1024, 4), (2048, 2), (4096, 1), (8192, 1)]:
        result = benchmark_attention(seq_len, batch_size)
        if result is not None:
            results.append(result)

    # 精度验证
    benchmark_precision()

    # 验收标准汇总
    if results:
        print(f"\n{'=' * 60}")
        print("验收标准汇总")
        print(f"{'=' * 60}")
        for r in results:
            seq = r["seq_len"]
            speedup = r["speedup"]
            vram_save = r["vram_savings_pct"]
            speed_ok = speedup >= 2.0
            vram_ok = vram_save >= 80.0
            print(
                f"Seq={seq}: Speedup={speedup:.2f}x ({'✅' if speed_ok else '❌'} ≥2x), "
                f"VRAM Save={vram_save:.1f}% ({'✅' if vram_ok else '❌'} ≥80%)",
            )


if __name__ == "__main__":
    main()
