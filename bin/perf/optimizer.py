"""
性能优化模块 - 整合所有优化策略
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标"""

    operation: str
    duration_ms: float
    memory_mb: float
    throughput: float | None = None
    extra: dict = field(default_factory=dict)


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self, log_dir: str = "./perf_logs"):
        self.metrics: list[PerformanceMetrics] = []
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def measure(self, operation: str):
        """性能测量上下文管理器"""
        torch.cuda.synchronize() if torch.cuda.is_available() else None
        start_time = time.perf_counter()
        start_mem = torch.cuda.memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0

        yield

        torch.cuda.synchronize() if torch.cuda.is_available() else None
        duration = (time.perf_counter() - start_time) * 1000
        end_mem = torch.cuda.memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0
        memory_mb = end_mem - start_mem

        metric = PerformanceMetrics(operation=operation, duration_ms=duration, memory_mb=memory_mb)
        self.metrics.append(metric)

        logger.debug(f"⏱️ {operation}: {duration:.2f}ms, 显存变化: {memory_mb:.2f}MB")

    def report(self) -> str:
        """生成性能报告"""
        if not self.metrics:
            return "无性能数据"

        report_lines = ["# 性能报告", ""]

        for metric in self.metrics:
            report_lines.append(
                f"- **{metric.operation}**: {metric.duration_ms:.2f}ms " f"(显存: {metric.memory_mb:.2f}MB)"
            )

        # 汇总
        total_time = sum(m.duration_ms for m in self.metrics)
        avg_time = total_time / len(self.metrics)
        report_lines.append("")
        report_lines.append("## 汇总")
        report_lines.append(f"- 总操作数: {len(self.metrics)}")
        report_lines.append(f"- 总耗时: {total_time:.2f}ms")
        report_lines.append(f"- 平均耗时: {avg_time:.2f}ms")

        return "\n".join(report_lines)

    def save_report(self, filename: str = "perf_report.md"):
        """保存性能报告"""
        report_path = self.log_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(self.report())
        logger.info(f"📊 性能报告已保存: {report_path}")


class ModelOptimizer:
    """模型优化器 - 整合多种优化策略"""

    @staticmethod
    def apply_torch_compile(model: nn.Module, mode: str = "reduce-overhead") -> nn.Module:
        """应用 torch.compile 优化"""
        try:
            optimized = torch.compile(model, mode=mode)
            logger.info(f"✅ torch.compile 优化已应用 (mode={mode})")
            return optimized
        except Exception as e:
            logger.warning(f"⚠️ torch.compile 失败: {e}")
            return model

    @staticmethod
    def apply_mixed_precision(model: nn.Module) -> nn.Module:
        """应用混合精度 (FP16/BF16)"""
        if torch.cuda.is_available():
            try:
                # BF16 优化 (Ampere+ GPU)
                if torch.cuda.is_bf16_supported():
                    model = model.to(torch.bfloat16)
                    logger.info("✅ BF16 精度已启用")
                else:
                    model = model.to(torch.float16)
                    logger.info("✅ FP16 精度已启用")
            except Exception as e:
                logger.warning(f"⚠️ 混合精度失败: {e}")
        return model

    @staticmethod
    def apply_gradient_checkpointing(model: nn.Module):
        """应用梯度检查点 - 节省显存"""
        try:
            if hasattr(model, "gradient_checkpointing_enable"):
                model.gradient_checkpointing_enable()
                logger.info("✅ 梯度检查点已启用")
            else:
                logger.warning("⚠️ 模型不支持梯度检查点")
        except Exception as e:
            logger.error(f"梯度检查点失败: {e}")

    @staticmethod
    def warmup_model(model: nn.Module, input_shape: tuple, num_iterations: int = 3):
        """模型预热 - 首次推理速度优化"""
        device = next(model.parameters()).device
        dummy_input = torch.randn(*input_shape, device=device)

        logger.info(f"🔥 模型预热中 ({num_iterations} 次)...")
        with torch.no_grad():
            for _ in range(num_iterations):
                _ = model(dummy_input)

        torch.cuda.synchronize() if torch.cuda.is_available() else None
        logger.info("✅ 模型预热完成")


# 全局监控器
perf_monitor = PerformanceMonitor()
