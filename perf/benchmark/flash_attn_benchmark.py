"""
Flash Attention 性能基准测试脚本
用于对比标准注意力 vs Flash Attention 2
"""

import json
import logging
import sys
import time
from pathlib import Path

import torch

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def benchmark_attention(seq_len: int, batch_size: int, n_heads: int = 8, head_dim: int = 64, n_iters: int = 50):
    """对比标准注意力和 Flash Attention 性能"""
    if not torch.cuda.is_available():
        logger.warning("CUDA 不可用，跳过性能测试")
        return

    device = "cuda"
    dim = n_heads * head_dim

    logger.info(f"配置: batch={batch_size}, seq_len={seq_len}, heads={n_heads}, head_dim={head_dim}")

    # 标准 PyTorch 注意力
    standard_attn = torch.nn.MultiheadAttention(dim, n_heads, batch_first=True).to(device)

    # Flash Attention (使用项目自实现的包装器)
    try:
        from bin.vram.flash_attention_wrapper import FlashAttention

        flash_attn = FlashAttention(dim, n_heads).to(device)
        has_flash = True
    except ImportError:
        logger.warning("Flash Attention 包装器不可用，仅测试标准注意力")
        has_flash = False

    # 准备输入
    x = torch.randn(batch_size, seq_len, dim, device=device)

    # 预热
    for _ in range(5):
        with torch.no_grad():
            _ = standard_attn(x, x, x)[0]
            if has_flash:
                _ = flash_attn(x)

    torch.cuda.synchronize()

    # 测试标准注意力
    start = time.perf_counter()
    for _ in range(n_iters):
        with torch.no_grad():
            _ = standard_attn(x, x, x)[0]
    torch.cuda.synchronize()
    standard_time = (time.perf_counter() - start) * 1000 / n_iters

    standard_mem = torch.cuda.max_memory_allocated() / 1024 / 1024
    torch.cuda.reset_peak_memory_stats()

    logger.info(f"标准注意力: {standard_time:.2f}ms/iter, 峰值显存: {standard_mem:.2f}MB")

    # 测试 Flash Attention
    if has_flash:
        start = time.perf_counter()
        for _ in range(n_iters):
            with torch.no_grad():
                _ = flash_attn(x)
        torch.cuda.synchronize()
        flash_time = (time.perf_counter() - start) * 1000 / n_iters

        flash_mem = torch.cuda.max_memory_allocated() / 1024 / 1024
        torch.cuda.reset_peak_memory_stats()

        logger.info(f"Flash Attention: {flash_time:.2f}ms/iter, 峰值显存: {flash_mem:.2f}MB")

        speedup = standard_time / flash_time
        mem_saving = (1 - flash_mem / standard_mem) * 100

        logger.info(f"✅ 加速比: {speedup:.2f}x")
        logger.info(f"✅ 显存节省: {mem_saving:.1f}%")

        return {
            "seq_len": seq_len,
            "batch_size": batch_size,
            "standard_time_ms": standard_time,
            "flash_time_ms": flash_time,
            "standard_memory_mb": standard_mem,
            "flash_memory_mb": flash_mem,
            "speedup": speedup,
            "memory_saving_pct": mem_saving,
        }

    return {
        "seq_len": seq_len,
        "batch_size": batch_size,
        "standard_time_ms": standard_time,
        "standard_memory_mb": standard_mem,
    }


def main():
    """主测试函数"""
    logger.info("🚀 开始 Flash Attention 性能测试")
    logger.info(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")

    test_configs = [
        (512, 4),
        (1024, 4),
        (2048, 2),
        (4096, 1),
    ]

    results = []
    for seq_len, batch_size in test_configs:
        try:
            result = benchmark_attention(seq_len, batch_size)
            results.append(result)
        except Exception as e:
            logger.error(f"测试 seq_len={seq_len} 失败: {e}")

    # 输出汇总
    logger.info("\n" + "=" * 60)
    logger.info("性能测试汇总")
    logger.info("=" * 60)
    for r in results:
        logger.info(json.dumps(r, indent=2, ensure_ascii=False))

    # 保存结果
    output_path = Path(__file__).parent / "flash_attn_benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"\n📊 结果已保存: {output_path}")


if __name__ == "__main__":
    main()
