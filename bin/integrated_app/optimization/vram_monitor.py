"""VRAM 峰值监控工具

参考 DiffBIR 显存峰值追踪器，提供细粒度的显存使用监控和峰值记录功能。
用于推理过程中追踪各阶段显存占用，帮助定位 OOM 瓶颈。

竞品来源: DiffBIR VRAMPeakMonitor
优先级: P1

Key Features:
- 分阶段显存峰值追踪（VAE编码/DiT采样/VAE解码/后处理）
- 自动内存快照与对比
- 上下文管理器风格的阶段标记
- 统一的监控报告生成
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import torch

logger = logging.getLogger(__name__)


@dataclass
class VRAMSnapshot:
    """某一时刻的显存快照"""
    timestamp: float
    stage: str
    allocated_mb: float
    reserved_mb: float
    peak_allocated_mb: float
    peak_reserved_mb: float
    free_mb: float
    total_mb: float


@dataclass
class VRAMStageStats:
    """一个阶段的显存统计"""
    stage_name: str
    start_time: float = 0.0
    end_time: float = 0.0
    start_allocated_mb: float = 0.0
    end_allocated_mb: float = 0.0
    peak_allocated_mb: float = 0.0
    peak_reserved_mb: float = 0.0
    snapshots: list[VRAMSnapshot] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    @property
    def delta_mb(self) -> float:
        return self.end_allocated_mb - self.start_allocated_mb


class VRAMPeakMonitor:
    """显存峰值监控器

    追踪推理各阶段的显存使用峰值，帮助定位 OOM 瓶颈。

    Usage:
        monitor = VRAMPeakMonitor()

        with monitor.stage("vae_encode"):
            vae.encode(x)

        with monitor.stage("dit_sample"):
            dit(x)

        report = monitor.get_report()
        monitor.reset()  # 推理完成后重置
    """

    def __init__(self, device: torch.device | str | None = None, enabled: bool = True):
        """初始化显存监控器

        Args:
            device: 监控的 GPU 设备，None 则使用 cuda:0
            enabled: 是否启用监控（生产环境可关闭以减少开销）
        """
        self.enabled = enabled
        if device is None:
            self.device = torch.device("cuda:0") if torch.cuda.is_available() else None
        elif isinstance(device, str):
            self.device = torch.device(device)
        else:
            self.device = device

        self._stages: list[VRAMStageStats] = []
        self._current_stage: VRAMStageStats | None = None
        self._global_peak_allocated_mb: float = 0.0
        self._global_peak_reserved_mb: float = 0.0
        self._inference_start_time: float = 0.0

    def _take_snapshot(self, stage: str) -> VRAMSnapshot | None:
        """拍摄当前显存快照"""
        if not self.enabled or self.device is None or not torch.cuda.is_available():
            return None

        try:
            allocated = torch.cuda.memory_allocated(self.device) / (1024 ** 2)
            reserved = torch.cuda.memory_reserved(self.device) / (1024 ** 2)
            peak_allocated = torch.cuda.max_memory_allocated(self.device) / (1024 ** 2)
            peak_reserved = torch.cuda.max_memory_reserved(self.device) / (1024 ** 2)

            free_mem, total_mem = torch.cuda.mem_get_info(self.device)
            free_mb = free_mem / (1024 ** 2)
            total_mb = total_mem / (1024 ** 2)

            return VRAMSnapshot(
                timestamp=time.time(),
                stage=stage,
                allocated_mb=allocated,
                reserved_mb=reserved,
                peak_allocated_mb=peak_allocated,
                peak_reserved_mb=peak_reserved,
                free_mb=free_mb,
                total_mb=total_mb,
            )
        except Exception as e:
            logger.debug(f"VRAM 快照失败: {e}")
            return None

    @contextmanager
    def stage(self, name: str):
        """阶段上下文管理器，自动记录阶段起止显存

        Args:
            name: 阶段名称 (e.g., "vae_encode", "dit_sample", "vae_decode")
        """
        if not self.enabled or self.device is None:
            yield
            return

        # 记录阶段开始
        stage_stats = VRAMStageStats(stage_name=name)
        stage_stats.start_time = time.time()

        snapshot = self._take_snapshot(name)
        if snapshot:
            stage_stats.snapshots.append(snapshot)
            stage_stats.start_allocated_mb = snapshot.allocated_mb

        self._current_stage = stage_stats
        logger.debug(f"[VRAM] 阶段开始: {name}, allocated={snapshot.allocated_mb:.1f}MB" if snapshot else f"[VRAM] 阶段开始: {name}")

        try:
            yield
        finally:
            # 记录阶段结束
            snapshot = self._take_snapshot(f"{name}_end")
            if snapshot:
                stage_stats.snapshots.append(snapshot)
                stage_stats.end_allocated_mb = snapshot.allocated_mb
                stage_stats.peak_allocated_mb = snapshot.peak_allocated_mb
                stage_stats.peak_reserved_mb = snapshot.peak_reserved_mb

                # 更新全局峰值
                self._global_peak_allocated_mb = max(self._global_peak_allocated_mb, snapshot.peak_allocated_mb)
                self._global_peak_reserved_mb = max(self._global_peak_reserved_mb, snapshot.peak_reserved_mb)

            stage_stats.end_time = time.time()
            self._stages.append(stage_stats)
            self._current_stage = None

            delta = stage_stats.delta_mb
            logger.debug(
                f"[VRAM] 阶段结束: {name}, "
                f"delta={delta:+.1f}MB, "
                f"duration={stage_stats.duration_ms:.0f}ms"
            )

    def snapshot(self, label: str = "") -> VRAMSnapshot | None:
        """手动拍摄快照（在阶段内使用）

        Args:
            label: 快照标签
        """
        name = label or (self._current_stage.stage_name if self._current_stage else "manual")
        snap = self._take_snapshot(name)
        if snap and self._current_stage:
            self._current_stage.snapshots.append(snap)
        return snap

    def start_inference(self):
        """开始一次推理追踪，重置峰值统计"""
        self._stages.clear()
        self._global_peak_allocated_mb = 0.0
        self._global_peak_reserved_mb = 0.0
        self._inference_start_time = time.time()

        if self.enabled and self.device is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(self.device)

    def end_inference(self):
        """结束一次推理追踪"""
        pass

    def get_report(self) -> dict:
        """生成显存监控报告

        Returns:
            包含各阶段统计和全局峰值的字典
        """
        stages = []
        for s in self._stages:
            stages.append({
                "stage": s.stage_name,
                "duration_ms": round(s.duration_ms, 1),
                "start_allocated_mb": round(s.start_allocated_mb, 1),
                "end_allocated_mb": round(s.end_allocated_mb, 1),
                "delta_mb": round(s.delta_mb, 1),
                "peak_allocated_mb": round(s.peak_allocated_mb, 1),
                "peak_reserved_mb": round(s.peak_reserved_mb, 1),
            })

        total_duration_ms = sum(s.duration_ms for s in self._stages)

        return {
            "global_peak_allocated_mb": round(self._global_peak_allocated_mb, 1),
            "global_peak_reserved_mb": round(self._global_peak_reserved_mb, 1),
            "total_duration_ms": round(total_duration_ms, 1),
            "num_stages": len(self._stages),
            "stages": stages,
        }

    def log_report(self):
        """将监控报告记录到日志"""
        report = self.get_report()
        logger.info(f"[VRAM 报告] 全局峰值: allocated={report['global_peak_allocated_mb']:.1f}MB, "
                     f"reserved={report['global_peak_reserved_mb']:.1f}MB, "
                     f"总耗时={report['total_duration_ms']:.0f}ms")
        for s in report["stages"]:
            logger.info(f"  {s['stage']}: delta={s['delta_mb']:+.1f}MB, "
                         f"peak={s['peak_allocated_mb']:.1f}MB, "
                         f"duration={s['duration_ms']:.0f}ms")

    def reset(self):
        """重置所有监控状态"""
        self._stages.clear()
        self._current_stage = None
        self._global_peak_allocated_mb = 0.0
        self._global_peak_reserved_mb = 0.0

        if self.enabled and self.device is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(self.device)
