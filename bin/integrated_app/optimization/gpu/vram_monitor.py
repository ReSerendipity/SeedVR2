"""VRAM 峰值监控工具模块 - SeedVR2 视频修复项目

本模块提供细粒度的 GPU 显存使用监控和峰值记录功能，参考 DiffBIR 的
VRAMPeakTracker 实现，用于在推理过程中分阶段追踪显存占用，帮助定位
OOM（Out of Memory）瓶颈和性能优化点。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch CUDA memory stats, contextlib, dataclasses, time

主要功能:
    - 分阶段显存峰值追踪（支持 VAE编码/DiT采样/VAE解码/后处理等任意阶段）
    - 自动显存快照与阶段间对比（显存增量、持续时间）
    - 上下文管理器风格的阶段标记（with 语句自动记录起止）
    - 手动快照 API（阶段内任意点采样）
    - 统一的监控报告生成（文本日志和结构化字典）
    - 监控开关（生产环境可禁用以减少开销）

典型使用场景:
    - 推理流程中诊断哪个阶段占用显存最多
    - 对比不同分辨率/模型大小/优化策略的显存占用
    - OOM 问题复现时定位具体触发点
    - BlockSwap 等优化功能的效果验证

参考来源:
    - DiffBIR VRAMPeakMonitor (P1 优先级)
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import torch

logger = logging.getLogger(__name__)


@dataclass
class VRAMSnapshot:
    """某一时刻的显存快照数据类

    记录单一时间点的完整显存状态，包括已分配、已保留、峰值、可用和总显存。

    Attributes:
        timestamp: 快照时间戳（Unix 时间，秒）
        stage: 快照所属阶段名称（如 "vae_encode", "dit_sample"）
        allocated_mb: PyTorch 已分配显存（MB，张量实际占用）
        reserved_mb: PyTorch 缓存分配器已保留显存（MB）
        peak_allocated_mb: 截至当前已分配显存的峰值（MB）
        peak_reserved_mb: 截至当前已保留显存的峰值（MB）
        free_mb: 驱动层面可用显存（MB，通过 mem_get_info 获取）
        total_mb: GPU 总显存（MB）
    """

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
    """一个推理阶段的显存统计数据类

    记录一个阶段（如 VAE 编码、DiT 采样）从开始到结束的完整显存使用情况，
    包括起止显存、峰值、持续时间和阶段内的多次快照。

    Attributes:
        stage_name: 阶段名称
        start_time: 阶段开始时间戳（秒）
        end_time: 阶段结束时间戳（秒）
        start_allocated_mb: 阶段开始时已分配显存（MB）
        end_allocated_mb: 阶段结束时已分配显存（MB）
        peak_allocated_mb: 阶段内已分配显存峰值（MB）
        peak_reserved_mb: 阶段内已保留显存峰值（MB）
        snapshots: 阶段内的所有显存快照列表
    """

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
        """阶段持续时间（毫秒）

        Returns:
            float: 阶段执行时长（毫秒）
        """
        return (self.end_time - self.start_time) * 1000

    @property
    def delta_mb(self) -> float:
        """阶段显存净增量（MB）

        阶段结束时与开始时的已分配显存差值，正值表示阶段内显存增长。

        Returns:
            float: 显存增量（MB），正值为增长，负值为减少
        """
        return self.end_allocated_mb - self.start_allocated_mb


class VRAMPeakMonitor:
    """显存峰值监控器

    追踪推理各阶段的显存使用峰值，帮助定位 OOM 瓶颈和验证显存优化效果。
    使用上下文管理器（context manager）风格标记阶段，自动记录起止显存状态。

    监控器支持启用/禁用，禁用时所有监控操作直接跳过，不产生任何开销，
    适合在生产环境中关闭以减少性能影响。

    Usage:
        monitor = VRAMPeakMonitor()
        monitor.start_inference()  # 开始一次推理追踪，重置峰值

        with monitor.stage("vae_encode"):
            vae.encode(x)  # VAE 编码阶段

        with monitor.stage("dit_sample"):
            dit(x)  # DiT 采样阶段（通常显存占用最高）

        with monitor.stage("vae_decode"):
            vae.decode(latent)  # VAE 解码阶段

        report = monitor.get_report()  # 获取结构化报告
        monitor.log_report()  # 或直接输出到日志
        monitor.reset()  # 推理完成后重置
    """

    def __init__(self, device: torch.device | str | None = None, enabled: bool = True):
        """初始化显存监控器

        Args:
            device: 监控的 GPU 设备
                - None: 自动选择 cuda:0（如果 CUDA 可用），否则为 None
                - str: 设备字符串（如 "cuda:0"）
                - torch.device: 设备对象
            enabled: 是否启用监控
                - True: 启用监控（默认）
                - False: 禁用监控，所有操作无开销跳过
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
        """拍摄当前显存状态快照（内部方法）

        Args:
            stage: 快照所属阶段名称

        Returns:
            VRAMSnapshot | None: 显存快照对象；
                监控禁用/CUDA不可用/查询失败时返回 None
        """
        if not self.enabled or self.device is None or not torch.cuda.is_available():
            return None

        try:
            allocated = torch.cuda.memory_allocated(self.device) / (1024**2)
            reserved = torch.cuda.memory_reserved(self.device) / (1024**2)
            peak_allocated = torch.cuda.max_memory_allocated(self.device) / (1024**2)
            peak_reserved = torch.cuda.max_memory_reserved(self.device) / (1024**2)

            # mem_get_info 返回 (free, total)，单位字节
            free_mem, total_mem = torch.cuda.mem_get_info(self.device)
            free_mb = free_mem / (1024**2)
            total_mb = total_mem / (1024**2)

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
        """阶段上下文管理器，自动记录阶段起止显存状态

        使用 with 语句包裹阶段代码，进入时记录开始显存和时间，
        退出时记录结束显存、峰值和持续时间，并更新全局峰值。

        Args:
            name: 阶段名称（如 "vae_encode", "dit_sample", "vae_decode", "postprocess"）

        Yields:
            None: with 语句体内执行阶段代码

        Example:
            with monitor.stage("dit_sample"):
                output = model(input_tensor)
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
        logger.debug(
            f"[VRAM] 阶段开始: {name}, allocated={snapshot.allocated_mb:.1f}MB"
            if snapshot
            else f"[VRAM] 阶段开始: {name}"
        )

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

                # 更新全局峰值（跨阶段追踪）
                self._global_peak_allocated_mb = max(self._global_peak_allocated_mb, snapshot.peak_allocated_mb)
                self._global_peak_reserved_mb = max(self._global_peak_reserved_mb, snapshot.peak_reserved_mb)

            stage_stats.end_time = time.time()
            self._stages.append(stage_stats)
            self._current_stage = None

            delta = stage_stats.delta_mb
            logger.debug(
                f"[VRAM] 阶段结束: {name}, " f"delta={delta:+.1f}MB, " f"duration={stage_stats.duration_ms:.0f}ms"
            )

    def snapshot(self, label: str = "") -> VRAMSnapshot | None:
        """手动拍摄显存快照（在阶段内使用）

        在阶段执行过程中手动记录某个关键点的显存状态，
        快照会自动添加到当前阶段的 snapshots 列表中。

        Args:
            label: 快照标签，为空时使用当前阶段名或 "manual"

        Returns:
            VRAMSnapshot | None: 快照对象；监控禁用/无当前阶段时可能返回 None
        """
        name = label or (self._current_stage.stage_name if self._current_stage else "manual")
        snap = self._take_snapshot(name)
        if snap and self._current_stage:
            self._current_stage.snapshots.append(snap)
        return snap

    def start_inference(self):
        """开始一次推理追踪，重置峰值统计和阶段列表

        应在每次推理任务开始前调用，清空之前的阶段数据并重置 CUDA 峰值统计。
        """
        self._stages.clear()
        self._global_peak_allocated_mb = 0.0
        self._global_peak_reserved_mb = 0.0
        self._inference_start_time = time.time()

        if self.enabled and self.device is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(self.device)

    def end_inference(self):
        """结束一次推理追踪（当前无额外操作，保留接口一致性）"""
        pass

    def get_report(self) -> dict:
        """生成显存监控结构化报告

        Returns:
            dict: 包含以下键的报告字典：
                - global_peak_allocated_mb (float): 全局已分配显存峰值（MB）
                - global_peak_reserved_mb (float): 全局已保留显存峰值（MB）
                - total_duration_ms (float): 所有阶段总耗时（毫秒）
                - num_stages (int): 阶段总数
                - stages (list[dict]): 各阶段统计列表，每个阶段包含：
                    - stage (str): 阶段名
                    - duration_ms (float): 阶段耗时（毫秒）
                    - start_allocated_mb (float): 开始时已分配显存
                    - end_allocated_mb (float): 结束时已分配显存
                    - delta_mb (float): 显存净增量
                    - peak_allocated_mb (float): 阶段内峰值
                    - peak_reserved_mb (float): 阶段内保留峰值
        """
        stages = []
        for s in self._stages:
            stages.append(
                {
                    "stage": s.stage_name,
                    "duration_ms": round(s.duration_ms, 1),
                    "start_allocated_mb": round(s.start_allocated_mb, 1),
                    "end_allocated_mb": round(s.end_allocated_mb, 1),
                    "delta_mb": round(s.delta_mb, 1),
                    "peak_allocated_mb": round(s.peak_allocated_mb, 1),
                    "peak_reserved_mb": round(s.peak_reserved_mb, 1),
                }
            )

        total_duration_ms = sum(s.duration_ms for s in self._stages)

        return {
            "global_peak_allocated_mb": round(self._global_peak_allocated_mb, 1),
            "global_peak_reserved_mb": round(self._global_peak_reserved_mb, 1),
            "total_duration_ms": round(total_duration_ms, 1),
            "num_stages": len(self._stages),
            "stages": stages,
        }

    def log_report(self):
        """将监控报告格式化输出到日志

        先输出全局峰值和总耗时，再逐阶段输出详情。
        日志级别为 INFO。
        """
        report = self.get_report()
        logger.info(
            f"[VRAM 报告] 全局峰值: allocated={report['global_peak_allocated_mb']:.1f}MB, "
            f"reserved={report['global_peak_reserved_mb']:.1f}MB, "
            f"总耗时={report['total_duration_ms']:.0f}ms"
        )
        for s in report["stages"]:
            logger.info(
                f"  {s['stage']}: delta={s['delta_mb']:+.1f}MB, "
                f"peak={s['peak_allocated_mb']:.1f}MB, "
                f"duration={s['duration_ms']:.0f}ms"
            )

    def reset(self):
        """重置所有监控状态，清空阶段数据和全局峰值

        可在多次推理之间调用以重置监控器状态。
        """
        self._stages.clear()
        self._current_stage = None
        self._global_peak_allocated_mb = 0.0
        self._global_peak_reserved_mb = 0.0

        if self.enabled and self.device is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(self.device)
