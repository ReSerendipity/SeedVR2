"""视频处理 / 帧插值增强模块

提供多种视频处理增强技术，包括帧插值、光流对齐、
深度感知处理、流式推理、帧分析和分层退化处理。

竞品来源:
- VEnhancer: 空间+时间+精炼一体化帧插值 (P1)
- Upscale-A-Video: RAFT 光流集成 (P2)
- DAIN: 深度感知帧插值 (P3)
- Stream-DiffVSR: 因果条件推理 (P3)
- Waifu2x-Extension-GUI: 视频帧分析 (P2)
- CogVideo: RIFE 帧插值参考 (P2)
- STAR: 分层退化处理 (P2)

Key Features:
- 空间+时间+精炼一体化处理: VEnhancer 风格的帧插值框架
- RAFT 光流估计: Upscale-A-Video 风格的帧运动估计与对齐
- 深度感知帧插值: DAIN 风格的深度感知流投影
- 因果条件推理: Stream-DiffVSR 风格的在线流式部署框架
- 重复帧检测与场景变化识别: Waifu2x-Extension-GUI 风格的帧分析
- RIFE 帧插值: CogVideo 风格的帧率增强参考
- 分层退化处理: STAR 风格的 light_deg/heavy_deg 退化预设
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 帧插值一体化框架 (VEnhancer inspired) - P1
# ---------------------------------------------------------------------------

class InterpolationStage(Enum):
    """帧插值处理阶段"""
    SPATIAL = "spatial"      # 空间超分辨率
    TEMPORAL = "temporal"    # 时间插帧
    REFINE = "refine"        # 精炼后处理


@dataclass
class VEnhancerConfig:
    """VEnhancer 一体化帧插值配置

    参考 VEnhancer 的 All-in-One 处理框架:
    将空间超分辨率、时间插帧和精炼后处理组合为统一流水线，
    一次处理即可同时完成空间增强和时间插帧。

    核心思想:
    - 空间阶段: 对输入帧进行超分辨率处理，提升空间细节
    - 时间阶段: 在超分辨率帧之间进行插帧，提升时间流畅度
    - 精炼阶段: 对插帧结果进行后处理，消除伪影和时序不连续
    - 三阶段共享特征提取器，避免重复计算
    """
    # 是否启用一体化帧插值
    enabled: bool = False
    # 空间放大倍数
    spatial_scale: float = 2.0
    # 时间插帧倍数 (帧率提升倍数)
    temporal_scale: int = 2
    # 是否启用精炼阶段
    use_refine: bool = True
    # 精炼迭代次数
    refine_iterations: int = 1
    # 处理阶段顺序
    stage_order: list[InterpolationStage] = field(
        default_factory=lambda: [
            InterpolationStage.SPATIAL,
            InterpolationStage.TEMPORAL,
            InterpolationStage.REFINE,
        ]
    )
    # 是否使用共享特征提取器
    shared_feature_extractor: bool = True
    # 中间特征缓存大小 (帧数)
    feature_cache_size: int = 4


class VEnhancerPipeline:
    """VEnhancer 一体化帧插值流水线

    参考 VEnhancer 的 All-in-One 处理流程:
    空间+时间+精炼三阶段协同处理。

    注意: 本实现为框架定义，核心推理逻辑需与实际模型集成。
    """

    def __init__(self, config: VEnhancerConfig):
        self.config = config
        self._feature_cache: dict[str, torch.Tensor] = {}

    def process_spatial(
        self,
        frames: torch.Tensor,
        model: nn.Module | None = None,
    ) -> torch.Tensor:
        """空间超分辨率阶段

        Args:
            frames: 输入帧 [B, T, C, H, W]
            model: 可选的超分辨率模型

        Returns:
            超分辨率帧 [B, T, C, H*scale, W*scale]
        """
        cfg = self.config
        if model is not None:
            # 使用模型进行超分辨率
            B, T, C, H, W = frames.shape
            flat_frames = frames.reshape(B * T, C, H, W)
            sr_frames = model(flat_frames)
            _, C_out, H_out, W_out = sr_frames.shape
            return sr_frames.reshape(B, T, C_out, H_out, W_out)

        # 无模型时使用双线性上采样
        B, T, C, H, W = frames.shape
        flat_frames = frames.reshape(B * T, C, H, W)
        up_frames = F.interpolate(
            flat_frames,
            scale_factor=cfg.spatial_scale,
            mode="bilinear",
            align_corners=False,
        )
        _, C_out, H_out, W_out = up_frames.shape
        return up_frames.reshape(B, T, C_out, H_out, W_out)

    def process_temporal(
        self,
        frames: torch.Tensor,
        flow_estimator: nn.Module | None = None,
    ) -> torch.Tensor:
        """时间插帧阶段

        Args:
            frames: 输入帧 [B, T, C, H, W]
            flow_estimator: 可选的光流估计模型

        Returns:
            插帧后的帧序列 [B, T*temporal_scale - (temporal_scale-1), C, H, W]
        """
        cfg = self.config
        B, T, C, H, W = frames.shape
        scale = cfg.temporal_scale

        # 在每对相邻帧之间插入 (scale-1) 个中间帧
        result_frames = []

        for t in range(T - 1):
            frame0 = frames[:, t]      # [B, C, H, W]
            frame1 = frames[:, t + 1]  # [B, C, H, W]
            result_frames.append(frame0)

            for i in range(1, scale):
                # 计算中间时刻
                t_mid = i / scale

                if flow_estimator is not None:
                    # 使用光流进行精确插帧
                    # 实际实现需要调用 flow_estimator 并进行双向 warp
                    mid_frame = self._flow_interpolate(
                        frame0, frame1, t_mid, flow_estimator
                    )
                else:
                    # 简单线性插值
                    mid_frame = (1 - t_mid) * frame0 + t_mid * frame1

                result_frames.append(mid_frame)

        # 添加最后一帧
        result_frames.append(frames[:, -1])

        return torch.stack(result_frames, dim=1)

    def _flow_interpolate(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
        t_mid: float,
        flow_estimator: nn.Module,
    ) -> torch.Tensor:
        """基于光流的帧插值

        Args:
            frame0: 前帧 [B, C, H, W]
            frame1: 后帧 [B, C, H, W]
            t_mid: 中间时刻 (0~1)
            flow_estimator: 光流估计模型

        Returns:
            中间帧 [B, C, H, W]
        """
        # 前向光流: frame0 → frame1
        flow_forward = flow_estimator(frame0, frame1)
        # 反向光流: frame1 → frame0
        flow_backward = flow_estimator(frame1, frame0)

        # 根据中间时刻缩放光流
        flow_mid_fwd = flow_forward * t_mid
        flow_mid_bwd = flow_backward * (1 - t_mid)

        # 双向 warp
        B, C, H, W = frame0.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(H, device=frame0.device, dtype=torch.float32),
            torch.arange(W, device=frame0.device, dtype=torch.float32),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1)  # [H, W, 2]
        grid = grid.unsqueeze(0).expand(B, -1, -1, -1)  # [B, H, W, 2]

        # 归一化到 [-1, 1]
        norm_grid_fwd = (grid + flow_mid_fwd.permute(0, 2, 3, 1)) * 2
        norm_grid_fwd[..., 0] = norm_grid_fwd[..., 0] / (W - 1) - 1
        norm_grid_fwd[..., 1] = norm_grid_fwd[..., 1] / (H - 1) - 1

        norm_grid_bwd = (grid + flow_mid_bwd.permute(0, 2, 3, 1)) * 2
        norm_grid_bwd[..., 0] = norm_grid_bwd[..., 0] / (W - 1) - 1
        norm_grid_bwd[..., 1] = norm_grid_bwd[..., 1] / (H - 1) - 1

        warped_fwd = F.grid_sample(
            frame0, norm_grid_fwd, mode="bilinear", align_corners=True
        )
        warped_bwd = F.grid_sample(
            frame1, norm_grid_bwd, mode="bilinear", align_corners=True
        )

        # 加权混合
        mid_frame = (1 - t_mid) * warped_fwd + t_mid * warped_bwd
        return mid_frame

    def process_refine(
        self,
        frames: torch.Tensor,
        refine_model: nn.Module | None = None,
    ) -> torch.Tensor:
        """精炼后处理阶段

        Args:
            frames: 插帧结果 [B, T, C, H, W]
            refine_model: 可选的精炼模型

        Returns:
            精炼后的帧序列
        """
        if refine_model is None:
            return frames

        B, T, C, H, W = frames.shape
        flat_frames = frames.reshape(B * T, C, H, W)
        refined = refine_model(flat_frames)
        _, C_out, H_out, W_out = refined.shape
        return refined.reshape(B, T, C_out, H_out, W_out)

    def __call__(
        self,
        frames: torch.Tensor,
        spatial_model: nn.Module | None = None,
        flow_estimator: nn.Module | None = None,
        refine_model: nn.Module | None = None,
    ) -> torch.Tensor:
        """执行完整的一体化帧插值流水线

        Args:
            frames: 输入帧 [B, T, C, H, W]
            spatial_model: 空间超分模型
            flow_estimator: 光流估计模型
            refine_model: 精炼模型

        Returns:
            处理后的帧序列
        """
        result = frames
        for stage in self.config.stage_order:
            if stage == InterpolationStage.SPATIAL:
                result = self.process_spatial(result, spatial_model)
            elif stage == InterpolationStage.TEMPORAL:
                result = self.process_temporal(result, flow_estimator)
            elif stage == InterpolationStage.REFINE:
                if self.config.use_refine:
                    result = self.process_refine(result, refine_model)
        return result


# ---------------------------------------------------------------------------
# RAFT 光流集成参考 (Upscale-A-Video inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class RAFTFlowConfig:
    """RAFT 光流集成配置

    参考 Upscale-A-Video 的 RAFT 光流应用:
    使用 RAFT (Recurrent All-Pairs Field Transforms) 进行帧间运动估计，
    获取精确的光流用于帧对齐和特征传播。

    核心思想:
    - RAFT 构建所有像素对的成本量 (cost volume)，迭代更新光流
    - 精确的光流用于: 帧对齐、特征传播、运动补偿
    - 在视频修复中，光流引导前一帧的特征对齐到当前帧位置
    """
    # 是否启用 RAFT 光流
    enabled: bool = False
    # RAFT 模型类型: 'sintel', 'kitti', 'things'
    model_type: str = "sintel"
    # 光流估计的小批量大小
    eval_batch_size: int = 1
    # 是否使用前向-后向一致性检查
    use_fb_check: bool = True
    # 前向-后向一致性阈值
    fb_check_threshold: float = 1.0
    # 是否缓存光流结果
    cache_flow: bool = True
    # 光流缓存最大帧数
    cache_max_frames: int = 120


class RAFTFlowEstimator:
    """RAFT 光流估计器

    参考 Upscale-A-Video 对 RAFT 的集成方式:
    提供统一的帧间光流估计接口，支持前向-后向一致性检查。

    注意: 本实现为参考框架，需要安装 raft-lite 或类似 RAFT 实现才能使用。
    """

    def __init__(self, config: RAFTFlowConfig):
        self.config = config
        self._model: nn.Module | None = None
        self._flow_cache: dict[tuple[int, int], torch.Tensor] = {}

    def load_model(self, model_path: str | None = None) -> bool:
        """加载 RAFT 模型

        Args:
            model_path: 模型权重路径

        Returns:
            是否成功加载
        """
        try:
            # RAFT 模型加载 (需要实际安装)
            # from raft import RAFT  # 需安装 raft 包
            # self._model = RAFT(...)
            logger.info("RAFT 光流模型加载为参考框架，需集成实际 RAFT 实现")
            return True
        except Exception as e:
            logger.error(f"RAFT 模型加载失败: {e}")
            return False

    def estimate_flow(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
    ) -> torch.Tensor:
        """估计帧间光流

        Args:
            frame0: 前帧 [B, C, H, W] 或 [C, H, W]
            frame1: 后帧 [B, C, H, W] 或 [C, H, W]

        Returns:
            光流张量 [B, 2, H, W]，通道 0 为 x 方向，通道 1 为 y 方向
        """
        if self._model is None:
            # 无模型时返回零光流
            if frame0.dim() == 3:
                H, W = frame0.shape[1:]
                return torch.zeros(2, H, W, device=frame0.device)
            else:
                B, _, H, W = frame0.shape
                return torch.zeros(B, 2, H, W, device=frame0.device)

        # 确保输入形状正确
        if frame0.dim() == 3:
            frame0 = frame0.unsqueeze(0)
            frame1 = frame1.unsqueeze(0)

        with torch.no_grad():
            flow = self._model(frame0, frame1)

        return flow

    def fb_consistency_check(
        self,
        flow_forward: torch.Tensor,
        flow_backward: torch.Tensor,
    ) -> torch.Tensor:
        """前向-后向一致性检查

        检测光流估计中的遮挡区域: 如果前向光流和后向光流不一致，
        说明该区域可能存在遮挡。

        Args:
            flow_forward: 前向光流 [B, 2, H, W]
            flow_backward: 反向光流 [B, 2, H, W]

        Returns:
            一致性掩码 [B, 1, H, W]，1.0 = 一致，0.0 = 遮挡
        """
        cfg = self.config

        # 使用前向光流 warp 后向光流
        B, _, H, W = flow_forward.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(H, device=flow_forward.device, dtype=torch.float32),
            torch.arange(W, device=flow_forward.device, dtype=torch.float32),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0).expand(B, -1, -1, -1)

        # Warp 后向光流到前向坐标系
        warped_backward = F.grid_sample(
            flow_backward,
            (grid + flow_forward.permute(0, 2, 3, 1)),
            mode="bilinear",
            align_corners=True,
        )

        # 计算一致性误差
        error = (flow_forward + warped_backward).norm(dim=1, keepdim=True)
        mask = (error < cfg.fb_check_threshold).float()

        return mask

    def clear_cache(self):
        """清除光流缓存"""
        self._flow_cache.clear()
        logger.debug("RAFT 光流缓存已清除")


# ---------------------------------------------------------------------------
# 深度感知帧插值参考 (DAIN inspired) - P3
# ---------------------------------------------------------------------------

@dataclass
class DepthAwareInterpConfig:
    """深度感知帧插值配置

    参考 DAIN (Depth-Aware Video Frame Interpolation) 的深度感知流投影:
    利用深度信息指导帧插值中的流投影，在遮挡区域和深度不连续处
    产生更准确的插帧结果。

    核心思想:
    - 传统帧插值在遮挡区域会产生伪影
    - 深度信息可以帮助判断前景/后景关系
    - 在深度不连续处 (遮挡边界) 使用深度感知的流融合权重
    - 前景物体的光流优先级高于后景
    """
    # 是否启用深度感知插帧
    enabled: bool = False
    # 深度估计模型类型: 'midas', 'zoedepth', 'depth_anything'
    depth_model: str = "midas"
    # 深度图分辨率 (与光流对齐)
    depth_resolution: tuple[int, int] = (256, 256)
    # 深度边缘阈值 (检测遮挡边界)
    depth_edge_threshold: float = 0.1
    # 前景流融合权重
    foreground_weight: float = 0.8
    # 后景流融合权重
    background_weight: float = 0.2


class DepthAwareInterpolator:
    """深度感知帧插值器

    参考 DAIN 的深度感知流投影方法:
    利用深度图指导光流融合，在遮挡区域产生更准确的插帧结果。

    注意: 本实现为参考框架，需要集成深度估计模型。
    """

    def __init__(self, config: DepthAwareInterpConfig):
        self.config = config
        self._depth_model: nn.Module | None = None

    def estimate_depth(self, frame: torch.Tensor) -> torch.Tensor:
        """估计单帧深度图

        Args:
            frame: 输入帧 [B, C, H, W]

        Returns:
            深度图 [B, 1, H, W]，值越大表示距离越近
        """
        if self._depth_model is None:
            # 无模型时返回均匀深度
            B, _, H, W = frame.shape
            return torch.ones(B, 1, H, W, device=frame.device) * 0.5

        with torch.no_grad():
            depth = self._depth_model(frame)

        # 归一化到 [0, 1]
        depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
        return depth

    def detect_depth_edges(self, depth: torch.Tensor) -> torch.Tensor:
        """检测深度图中的边缘 (遮挡边界)

        Args:
            depth: 深度图 [B, 1, H, W]

        Returns:
            边缘掩码 [B, 1, H, W]，1.0 = 边缘
        """
        cfg = self.config

        # Sobel 边缘检测
        sobel_x = torch.tensor(
            [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]],
            dtype=torch.float32, device=depth.device,
        ).reshape(1, 1, 3, 3)
        sobel_y = sobel_x.permute(0, 1, 3, 2)

        grad_x = F.conv2d(depth, sobel_x, padding=1)
        grad_y = F.conv2d(depth, sobel_y, padding=1)
        grad_mag = (grad_x ** 2 + grad_y ** 2).sqrt()

        edges = (grad_mag > cfg.depth_edge_threshold).float()
        return edges

    def compute_depth_aware_weights(
        self,
        depth0: torch.Tensor,
        depth1: torch.Tensor,
    ) -> torch.Tensor:
        """计算深度感知的融合权重

        在遮挡边界处，前景物体的光流应获得更高权重。

        Args:
            depth0: 前帧深度图 [B, 1, H, W]
            depth1: 后帧深度图 [B, 1, H, W]

        Returns:
            融合权重 [B, 1, H, W]，值越大表示前帧权重越高
        """
        cfg = self.config

        # 深度值越大 = 距离越近 = 前景
        # 前景区域使用更高的前帧权重
        foreground_mask = (depth0 > 0.5).float()

        # 在遮挡边界处使用混合权重
        edges = self.detect_depth_edges(depth0)

        weights = (
            foreground_mask * cfg.foreground_weight
            + (1 - foreground_mask) * cfg.background_weight
        )

        # 在边缘区域平滑过渡
        weights = weights * (1 - edges) + 0.5 * edges

        return weights

    def _depth_flow_projection(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
        flow_forward: torch.Tensor,
        flow_backward: torch.Tensor,
        depth0: torch.Tensor,
        depth1: torch.Tensor,
        t_mid: float = 0.5,
    ) -> torch.Tensor:
        """深度感知流投影 (DAIN 核心逻辑)

        参考 DAIN (Depth-Aware Video Frame Interpolation) 的流投影方法:
        利用深度信息解决帧插值中的遮挡 (occlusion) 问题。

        核心流程:
        1. 深度边缘检测 — 识别深度不连续区域 (前景/后景分界)
        2. 遮挡区域识别 — 结合光流前向-后向一致性与深度边缘，
           判断哪些像素在前向 warp 后被遮挡
        3. 流投影 — 非遮挡区域使用前向流 warp，遮挡区域使用反向流
           (即从后帧向中间时刻投影，绕过遮挡)

        设计说明:
        - 旧版 DAIN 使用 CUDA 扩展 (depth_awre_flow_projection) 实现流投影，
          该 CUDA 扩展已过时，仅参考设计模式。
        - 本实现用纯 PyTorch 操作模拟同等逻辑，标注 TODO 处待接入
          真实深度估计模型以获得更精确的深度图。

        Args:
            frame0: 前帧 [B, C, H, W]
            frame1: 后帧 [B, C, H, W]
            flow_forward: 前向光流 (frame0→frame1) [B, 2, H, W]
            flow_backward: 反向光流 (frame1→frame0) [B, 2, H, W]
            depth0: 前帧深度图 [B, 1, H, W]，值越大距离越近
            depth1: 后帧深度图 [B, 1, H, W]，值越大距离越近
            t_mid: 中间时刻 (0=前帧, 1=后帧)

        Returns:
            插值帧 [B, C, H, W]
        """
        cfg = self.config
        B, C, H, W = frame0.shape
        device = frame0.device

        # ---- 步骤 1: 深度边缘检测 ----
        # 深度不连续处 = 遮挡边界候选区域
        depth_edges0 = self.detect_depth_edges(depth0)   # [B, 1, H, W]
        depth_edges1 = self.detect_depth_edges(depth1)   # [B, 1, H, W]

        # ---- 步骤 2: 遮挡区域识别 ----
        # 前向遮挡: frame0 中的像素经 flow_forward 投影到中间时刻时，
        # 如果目标位置已有更近 (depth 更大) 的像素，则该像素被遮挡。
        # 用前向-后向一致性近似判断遮挡:
        #   warp(flow_backward, flow_forward) ≈ -flow_forward 时一致，
        #   否则存在遮挡。
        grid_y, grid_x = torch.meshgrid(
            torch.arange(H, device=device, dtype=torch.float32),
            torch.arange(W, device=device, dtype=torch.float32),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1)          # [H, W, 2]
        grid = grid.unsqueeze(0).expand(B, -1, -1, -1)        # [B, H, W, 2]

        # 缩放光流到中间时刻
        flow_fwd_scaled = flow_forward * t_mid                 # [B, 2, H, W]
        flow_bwd_scaled = flow_backward * (1 - t_mid)          # [B, 2, H, W]

        # 构造采样网格 (归一化到 [-1, 1] 以配合 grid_sample)
        def _make_sample_grid(base_grid: torch.Tensor, flow: torch.Tensor) -> torch.Tensor:
            """将像素坐标 + 光流转换为 grid_sample 所需的归一化坐标"""
            coords = base_grid + flow.permute(0, 2, 3, 1)      # [B, H, W, 2]
            norm_coords = coords.clone()
            norm_coords[..., 0] = norm_coords[..., 0] / (W - 1) * 2 - 1
            norm_coords[..., 1] = norm_coords[..., 1] / (H - 1) * 2 - 1
            return norm_coords

        # 从 frame0 warp 到中间时刻 (前向投影)
        grid_fwd = _make_sample_grid(grid, flow_fwd_scaled)
        warped0 = F.grid_sample(frame0, grid_fwd, mode="bilinear", align_corners=True)

        # 从 frame1 warp 到中间时刻 (反向投影)
        grid_bwd = _make_sample_grid(grid, flow_bwd_scaled)
        warped1 = F.grid_sample(frame1, grid_bwd, mode="bilinear", align_corners=True)

        # 同样 warp 深度图到中间时刻，用于判断遮挡
        warped_depth0 = F.grid_sample(depth0, grid_fwd, mode="bilinear", align_corners=True)
        warped_depth1 = F.grid_sample(depth1, grid_bwd, mode="bilinear", align_corners=True)

        # 遮挡掩码: 在中间时刻，如果 warped_depth0 < warped_depth1，
        # 说明 frame0 的投影被 frame1 的投影遮挡 (frame1 更近)
        # occlusion0 = 1 表示 frame0 的该像素被遮挡，应使用反向投影
        # TODO: 接入真实深度估计模型后，此遮挡判断将更精确
        occlusion0 = (warped_depth0 < warped_depth1).float()   # [B, 1, H, W]
        occlusion1 = (warped_depth1 <= warped_depth0).float()  # [B, 1, H, W]

        # 在深度边缘区域，增强遮挡掩码的权重
        # (深度不连续处更可能出现遮挡误判，需更保守地混合)
        edge_mask = torch.clamp(depth_edges0 + depth_edges1, 0, 1)  # [B, 1, H, W]

        # ---- 步骤 3: 深度感知流投影融合 ----
        # 非遮挡区域: 正常加权融合
        # 遮挡区域: 仅使用非遮挡方向的投影
        # 深度边缘区域: 使用深度感知权重平滑过渡

        depth_aware_weights = self.compute_depth_aware_weights(depth0, depth1)  # [B, 1, H, W]

        # 基础融合权重: 前帧权重 = depth_aware_weights, 后帧权重 = 1 - depth_aware_weights
        w0 = depth_aware_weights       # [B, 1, H, W]
        w1 = 1 - depth_aware_weights   # [B, 1, H, W]

        # 在遮挡区域修正权重:
        # 若 frame0 被遮挡 → 降低 w0，提高 w1
        # 若 frame1 被遮挡 → 降低 w1，提高 w0
        w0 = w0 * (1 - occlusion0) + 0.0 * occlusion0
        w1 = w1 * (1 - occlusion1) + 0.0 * occlusion1

        # 在深度边缘区域使用更保守的 0.5 权重平滑过渡
        w0 = w0 * (1 - edge_mask) + 0.5 * edge_mask
        w1 = w1 * (1 - edge_mask) + 0.5 * edge_mask

        # 归一化权重
        weight_sum = w0 + w1 + 1e-8
        w0 = w0 / weight_sum
        w1 = w1 / weight_sum

        # 加权融合两方向的投影结果
        mid_frame = w0 * warped0 + w1 * warped1   # [B, C, H, W]

        # 处理 warp 后可能超出边界的像素 (用原始帧线性插值填充)
        # 检测有效区域: warp 后坐标在画面内
        valid_fwd = (
            (grid_fwd[..., 0] >= -1) & (grid_fwd[..., 0] <= 1) &
            (grid_fwd[..., 1] >= -1) & (grid_fwd[..., 1] <= 1)
        ).unsqueeze(1).float()                     # [B, 1, H, W]
        valid_bwd = (
            (grid_bwd[..., 0] >= -1) & (grid_bwd[..., 0] <= 1) &
            (grid_bwd[..., 1] >= -1) & (grid_bwd[..., 1] <= 1)
        ).float().unsqueeze(1)                     # [B, 1, H, W]
        valid_mask = torch.clamp(valid_fwd + valid_bwd, 0, 1)

        # 对无效区域用简单线性插值兜底
        fallback = (1 - t_mid) * frame0 + t_mid * frame1
        mid_frame = valid_mask * mid_frame + (1 - valid_mask) * fallback

        return mid_frame

    def interpolate(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
        flow_forward: torch.Tensor,
        flow_backward: torch.Tensor,
        t_mid: float = 0.5,
    ) -> torch.Tensor:
        """深度感知帧插值

        Args:
            frame0: 前帧 [B, C, H, W]
            frame1: 后帧 [B, C, H, W]
            flow_forward: 前向光流 [B, 2, H, W]
            flow_backward: 反向光流 [B, 2, H, W]
            t_mid: 中间时刻

        Returns:
            插值帧 [B, C, H, W]
        """
        depth0 = self.estimate_depth(frame0)
        depth1 = self.estimate_depth(frame1)

        # 使用深度感知流投影替代简单加权混合
        mid_frame = self._depth_flow_projection(
            frame0, frame1,
            flow_forward, flow_backward,
            depth0, depth1,
            t_mid,
        )

        return mid_frame


# ---------------------------------------------------------------------------
# 因果条件推理 (Stream-DiffVSR inspired) - P3
# ---------------------------------------------------------------------------

@dataclass
class CausalInferenceConfig:
    """因果条件推理配置

    参考 Stream-DiffVSR 的因果条件推理机制:
    仅使用过去帧进行条件推理，实现真正的在线流式部署，
    无需等待未来帧即可开始生成。

    核心思想:
    - 传统视频修复需要双向 (过去+未来) 帧作为条件
    - 因果推理仅使用过去帧，实现低延迟流式处理
    - 通过因果注意力掩码确保模型只能看到当前和过去的帧
    - 适用于实时视频修复、直播增强等场景
    """
    # 是否启用因果推理模式
    enabled: bool = False
    # 因果历史窗口大小 (使用多少个过去帧)
    history_window: int = 3
    # 是否使用因果注意力掩码
    use_causal_mask: bool = True
    # 流式缓冲区大小
    stream_buffer_size: int = 8
    # 是否启用增量推理 (仅处理新帧)
    incremental_mode: bool = True
    # 初始预热帧数 (前 N 帧使用双向模式)
    warmup_frames: int = 2


class CausalInferenceEngine:
    """因果条件推理引擎

    参考 Stream-DiffVSR 的在线流式推理:
    仅使用过去帧进行条件推理，支持低延迟流式部署。

    注意: 本实现为框架定义，实际推理逻辑需与 DiT 模型集成。
    """

    def __init__(self, config: CausalInferenceConfig):
        self.config = config
        self._frame_buffer: list[torch.Tensor] = []
        self._feature_buffer: list[torch.Tensor] = []
        self._frame_count = 0

    def create_causal_mask(
        self,
        seq_len: int,
        num_frames: int,
        device: torch.device | str = "cpu",
    ) -> torch.Tensor:
        """创建因果注意力掩码

        确保每帧只能注意自身及之前的帧，不能看到未来帧。

        Args:
            seq_len: 每帧的 token 数
            num_frames: 帧数
            device: 设备

        Returns:
            因果掩码 [total_seq, total_seq]，1.0 = 允许注意，0.0 = 遮蔽
        """
        total_len = seq_len * num_frames

        # 帧级因果掩码
        frame_mask = torch.ones(num_frames, num_frames, device=device)
        frame_mask = torch.tril(frame_mask)  # 下三角 = 因果

        # 扩展到 token 级别
        token_mask = frame_mask.unsqueeze(1).unsqueeze(2).expand(
            -1, seq_len, -1, seq_len
        ).reshape(total_len, total_len)

        return token_mask

    def push_frame(self, frame: torch.Tensor) -> None:
        """推入新帧到缓冲区

        Args:
            frame: 新帧 [C, H, W]
        """
        self._frame_buffer.append(frame)
        self._frame_count += 1

        # 维护固定大小的缓冲区
        if len(self._frame_buffer) > self.config.stream_buffer_size:
            self._frame_buffer.pop(0)

    def get_condition_frames(self) -> list[torch.Tensor]:
        """获取用于条件推理的历史帧

        Returns:
            历史帧列表，按时间顺序排列
        """
        window = self.config.history_window
        # 取最近 window 个帧
        start_idx = max(0, len(self._frame_buffer) - window)
        return self._frame_buffer[start_idx:]

    def is_warmup_complete(self) -> bool:
        """预热阶段是否完成

        在预热阶段使用双向模式以获得更稳定的初始结果。
        """
        return self._frame_count > self.config.warmup_frames

    def _causal_condition_inference(
        self,
        current_frame: torch.Tensor,
        model: nn.Module | None = None,
        condition_encoder: nn.Module | None = None,
    ) -> torch.Tensor:
        """因果条件推理 (Stream-DiffVSR 核心逻辑)

        参考 Stream-DiffVSR 的因果条件推理机制:
        仅使用过去帧 (past frames) 作为条件进行推理，不依赖任何未来帧，
        从而实现真正的在线流式部署 (online streaming deployment)。

        核心流程:
        1. 条件构建 — 从帧缓冲区中取出最近的历史帧，仅包含当前帧及
           过去的帧，严格排除未来帧
        2. 预热阶段 — 前几帧使用双向模式 (过去+未来) 以获得更稳定的
           初始结果；预热完成后切换为纯因果模式
        3. 因果注意力 — 在模型推理时施加因果注意力掩码，确保每个时间步
           只能注意自身及之前的帧特征
        4. 增量推理 — 当 incremental_mode 启用时，仅对新帧进行推理，
           复用之前缓存的特征，减少重复计算

        设计说明:
        - Stream-DiffVSR 原论文使用 DiT 架构的因果注意力实现流式推理，
          本实现为框架级代码，标注 TODO 处待接入实际 DiT 模型。
        - 因果掩码通过 create_causal_mask 方法生成，可直接应用于
          torch.nn.MultiheadAttention 的 attn_mask 参数。

        Args:
            current_frame: 当前待推理帧 [C, H, W]
            model: 推理模型 (如 DiT)，需支持 causal_mask 参数；
                   为 None 时使用简单的帧加权融合作为占位
            condition_encoder: 条件编码器，将历史帧编码为条件特征；
                   为 None 时直接使用帧像素作为条件

        Returns:
            推理结果帧 [C, H, W]
        """
        cfg = self.config
        C, H, W = current_frame.shape
        device = current_frame.device

        # ---- 步骤 1: 将当前帧推入缓冲区并构建因果条件 ----
        self.push_frame(current_frame)

        # 获取历史条件帧 (仅过去帧，不含未来帧)
        condition_frames = self.get_condition_frames()  # list[Tensor], 每帧 [C, H, W]
        num_cond = len(condition_frames)

        if num_cond == 0:
            # 缓冲区为空 (不应发生)，直接返回当前帧
            return current_frame

        # ---- 步骤 2: 预热阶段判断 ----
        is_warmup = not self.is_warmup_complete()

        if is_warmup:
            # 预热阶段: 使用双向模式以获得更稳定的初始结果
            # 在双向模式下，条件帧包含更多历史信息 (若可用)
            # 但仍然不使用未来帧 — 仅增大历史窗口
            warmup_window = min(
                cfg.warmup_frames + cfg.history_window,
                len(self._frame_buffer),
            )
            warmup_start = max(0, len(self._frame_buffer) - warmup_window)
            condition_frames = self._frame_buffer[warmup_start:]
            num_cond = len(condition_frames)

        # ---- 步骤 3: 条件编码 ----
        # 将历史帧编码为条件特征
        # TODO: 接入真实条件编码器 (如 Stream-DiffVSR 的 CLIP/VAE 编码器)
        if condition_encoder is not None:
            # 使用编码器: 将各帧编码为条件特征
            cond_stack = torch.stack(condition_frames, dim=0)   # [T_cond, C, H, W]
            cond_features = condition_encoder(cond_stack)       # [T_cond, D, h, w]
        else:
            # 无编码器时直接使用帧像素 (降采样以减少计算量)
            cond_stack = torch.stack(condition_frames, dim=0)   # [T_cond, C, H, W]
            # 简单降采样到 1/4 分辨率作为伪特征
            cond_downsampled = F.avg_pool2d(
                cond_stack, kernel_size=4, stride=4,
            )  # [T_cond, C, H/4, W/4]
            cond_features = cond_downsampled                   # [T_cond, C, H/4, W/4]

        # 缓存当前帧的条件特征 (用于增量推理)
        self._feature_buffer.append(cond_features[-1])
        if len(self._feature_buffer) > cfg.stream_buffer_size:
            self._feature_buffer.pop(0)

        # ---- 步骤 4: 因果注意力掩码 ----
        # 创建帧级因果掩码: 每个时间步只能注意自身及之前的帧
        if cfg.use_causal_mask and model is not None:
            # 计算每帧的 token 数 (特征的空间维度展平)
            T_cond, D_feat, h_feat, w_feat = cond_features.shape
            tokens_per_frame = h_feat * w_feat
            causal_mask = self.create_causal_mask(
                seq_len=tokens_per_frame,
                num_frames=T_cond,
                device=device,
            )  # [T_cond * tokens_per_frame, T_cond * tokens_per_frame]
        else:
            causal_mask = None

        # ---- 步骤 5: 模型推理 ----
        if model is not None:
            # 使用模型进行推理
            # TODO: 接入实际 DiT 模型，传入 causal_mask 作为 attn_mask
            #   output = model(
            #       current_frame,
            #       condition=cond_features,
            #       causal_mask=causal_mask,
            #   )
            # 当前作为框架占位: 将条件特征简单聚合后与当前帧加权
            with torch.no_grad():
                # 占位推理: 条件特征的均值作为全局条件
                # 实际应由 DiT 模型完成
                global_cond = cond_features.mean(dim=0)  # [D, h, w]
                # 简单上采样回原分辨率
                global_cond_up = F.interpolate(
                    global_cond.unsqueeze(0),
                    size=(H, W),
                    mode="bilinear",
                    align_corners=False,
                ).squeeze(0)  # [D, H, W]
                # 取前 C 通道与当前帧混合
                cond_for_mix = global_cond_up[:C] if global_cond_up.shape[0] >= C else global_cond_up
                result_frame = 0.7 * current_frame + 0.3 * cond_for_mix[:C, :, :]
        else:
            # 无模型时使用历史帧的时间加权融合
            # 越近的帧权重越高 (指数衰减)
            weights = torch.tensor(
                [0.5 ** (num_cond - 1 - i) for i in range(num_cond)],
                dtype=torch.float32,
                device=device,
            )
            weights = weights / weights.sum()

            result_frame = torch.zeros_like(current_frame)
            for i, frame in enumerate(condition_frames):
                result_frame += weights[i] * frame

            # 混合当前帧 (保证当前帧有最高权重)
            result_frame = 0.6 * current_frame + 0.4 * result_frame

        # ---- 步骤 6: 增量推理标记 ----
        # 增量模式下，后续调用仅处理新帧，复用已缓存的特征
        # (本框架已通过 _feature_buffer 自动管理)
        if cfg.incremental_mode and not is_warmup:
            logger.debug(
                f"因果增量推理: 帧 #{self._frame_count}, "
                f"条件帧数={num_cond}, 预热={'是' if is_warmup else '否'}"
            )

        return result_frame

    def reset(self) -> None:
        """重置引擎状态"""
        self._frame_buffer.clear()
        self._feature_buffer.clear()
        self._frame_count = 0
        logger.debug("因果推理引擎已重置")


# ---------------------------------------------------------------------------
# 视频帧分析 (Waifu2x-Extension-GUI inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class FrameAnalysisConfig:
    """视频帧分析配置

    参考 Waifu2x-Extension-GUI 的帧分析功能:
    检测重复帧和场景变化，避免对冗余帧进行不必要的处理。

    核心思想:
    - 动画/游戏视频存在大量重复帧 (低帧率素材)
    - 重复帧不需要重复处理，可以复用之前的结果
    - 场景切换点需要特殊处理 (不能跨场景做时序对齐)
    """
    # 是否启用帧分析
    enabled: bool = True
    # 重复帧检测阈值: 帧间 MSE 低于此值视为重复帧
    duplicate_threshold: float = 0.001
    # 场景变化检测阈值: 帧间 MSE 高于此值视为场景切换
    scene_change_threshold: float = 0.3
    # 是否使用结构相似性 (SSIM) 代替 MSE
    use_ssim: bool = False
    # SSIM 场景变化阈值
    ssim_scene_threshold: float = 0.85
    # 是否缓存分析结果
    cache_results: bool = True


@dataclass
class FrameAnalysisResult:
    """帧分析结果"""
    # 帧索引
    frame_idx: int
    # 是否为重复帧
    is_duplicate: bool
    # 参考帧索引 (如果是重复帧，指向原始帧)
    reference_frame_idx: int | None
    # 是否为场景切换点
    is_scene_change: bool
    # 与前一帧的相似度分数
    similarity_score: float


class FrameAnalyzer:
    """视频帧分析器

    参考 Waifu2x-Extension-GUI 的帧分析功能:
    检测重复帧和场景变化，优化视频处理流水线。
    """

    def __init__(self, config: FrameAnalysisConfig):
        self.config = config
        self._results: dict[int, FrameAnalysisResult] = {}

    def compute_mse(self, frame0: torch.Tensor, frame1: torch.Tensor) -> float:
        """计算两帧之间的 MSE

        Args:
            frame0: 帧 [C, H, W]
            frame1: 帧 [C, H, W]

        Returns:
            MSE 值
        """
        mse = F.mse_loss(frame0.float(), frame1.float()).item()
        return mse

    def compute_ssim(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
        window_size: int = 11,
    ) -> float:
        """计算两帧之间的 SSIM

        简化版 SSIM 计算，用于场景变化检测。

        Args:
            frame0: 帧 [C, H, W]
            frame1: 帧 [C, H, W]
            window_size: 窗口大小

        Returns:
            SSIM 值 (0~1)
        """
        C = frame0.shape[0]

        # 转为灰度简化计算
        if C == 3:
            gray0 = 0.299 * frame0[0] + 0.587 * frame0[1] + 0.114 * frame0[2]
            gray1 = 0.299 * frame1[0] + 0.587 * frame1[1] + 0.114 * frame1[2]
        else:
            gray0 = frame0.mean(dim=0)
            gray1 = frame1.mean(dim=0)

        gray0 = gray0.unsqueeze(0).unsqueeze(0)
        gray1 = gray1.unsqueeze(0).unsqueeze(0)

        # 均值
        mu0 = F.avg_pool2d(gray0, window_size, stride=1, padding=window_size // 2)
        mu1 = F.avg_pool2d(gray1, window_size, stride=1, padding=window_size // 2)

        mu0_sq = mu0 ** 2
        mu1_sq = mu1 ** 2
        mu01 = mu0 * mu1

        # 方差和协方差
        sigma0_sq = F.avg_pool2d(gray0 ** 2, window_size, stride=1, padding=window_size // 2) - mu0_sq
        sigma1_sq = F.avg_pool2d(gray1 ** 2, window_size, stride=1, padding=window_size // 2) - mu1_sq
        sigma01 = F.avg_pool2d(gray0 * gray1, window_size, stride=1, padding=window_size // 2) - mu01

        C1 = 0.01 ** 2
        C2 = 0.03 ** 2

        ssim_map = ((2 * mu01 + C1) * (2 * sigma01 + C2)) / (
            (mu0_sq + mu1_sq + C1) * (sigma0_sq + sigma1_sq + C2)
        )

        return ssim_map.mean().item()

    def analyze_frame(
        self,
        current_frame: torch.Tensor,
        previous_frame: torch.Tensor | None,
        frame_idx: int,
    ) -> FrameAnalysisResult:
        """分析单帧

        Args:
            current_frame: 当前帧 [C, H, W]
            previous_frame: 前一帧 [C, H, W] (第一帧为 None)
            frame_idx: 帧索引

        Returns:
            帧分析结果
        """
        cfg = self.config

        if previous_frame is None:
            # 第一帧
            result = FrameAnalysisResult(
                frame_idx=frame_idx,
                is_duplicate=False,
                reference_frame_idx=None,
                is_scene_change=True,  # 第一帧视为场景开始
                similarity_score=1.0,
            )
            self._results[frame_idx] = result
            return result

        # 计算相似度
        if cfg.use_ssim:
            similarity = self.compute_ssim(current_frame, previous_frame)
            # SSIM 越高越相似
            is_duplicate = similarity > cfg.ssim_scene_threshold
            is_scene_change = similarity < (1 - cfg.ssim_scene_threshold)
        else:
            mse = self.compute_mse(current_frame, previous_frame)
            similarity = 1.0 - min(mse, 1.0)  # 转为相似度
            is_duplicate = mse < cfg.duplicate_threshold
            is_scene_change = mse > cfg.scene_change_threshold

        # 查找参考帧
        reference_idx = None
        if is_duplicate:
            # 找到最近的非重复帧
            for prev_idx in range(frame_idx - 1, -1, -1):
                if prev_idx in self._results and not self._results[prev_idx].is_duplicate:
                    reference_idx = prev_idx
                    break

        result = FrameAnalysisResult(
            frame_idx=frame_idx,
            is_duplicate=is_duplicate,
            reference_frame_idx=reference_idx,
            is_scene_change=is_scene_change,
            similarity_score=similarity,
        )
        self._results[frame_idx] = result
        return result

    def analyze_video(
        self,
        frames: list[torch.Tensor],
    ) -> list[FrameAnalysisResult]:
        """分析整个视频的帧序列

        Args:
            frames: 帧列表，每帧 [C, H, W]

        Returns:
            分析结果列表
        """
        self._results.clear()
        results = []

        for i, frame in enumerate(frames):
            prev_frame = frames[i - 1] if i > 0 else None
            result = self.analyze_frame(frame, prev_frame, i)
            results.append(result)

        # 统计
        num_duplicates = sum(1 for r in results if r.is_duplicate)
        num_scene_changes = sum(1 for r in results if r.is_scene_change)
        logger.info(
            f"帧分析完成: {len(frames)} 帧, "
            f"{num_duplicates} 重复帧 ({num_duplicates / len(frames) * 100:.1f}%), "
            f"{num_scene_changes} 场景切换"
        )

        return results

    def get_duplicate_groups(self) -> dict[int, list[int]]:
        """获取重复帧分组

        Returns:
            字典: key = 参考帧索引, value = 重复帧索引列表
        """
        groups: dict[int, list[int]] = {}
        for idx, result in self._results.items():
            if result.is_duplicate and result.reference_frame_idx is not None:
                ref = result.reference_frame_idx
                if ref not in groups:
                    groups[ref] = []
                groups[ref].append(idx)
        return groups

    def clear_cache(self) -> None:
        """清除分析缓存"""
        self._results.clear()


# ---------------------------------------------------------------------------
# RIFE 帧插值参考 (CogVideo inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class RIFEInterpConfig:
    """RIFE 帧插值配置

    参考 CogVideo 对 RIFE (Real-Time Intermediate Flow Estimation) 的集成:
    RIFE 是一种实时帧插值方法，通过直接估计中间帧的光流实现高效插帧。

    核心思想:
    - RIFE 不估计前向/后向光流，而是直接估计中间时刻的光流
    - 使用 Coarse-to-Fine 结构逐步精细化光流
    - 相比双向光流方法，RIFE 在遮挡区域表现更优
    - 推理速度快，适合实时处理
    """
    # 是否启用 RIFE 帧插值
    enabled: bool = False
    # RIFE 模型版本: 'rife4', 'rife2'
    model_version: str = "rife4"
    # 插帧倍数
    interpolation_factor: int = 2
    # 是否使用 U-Head (更精细的光流估计)
    use_uhead: bool = True
    # 推理精度
    dtype: str = "float16"


class RIFEInterpolator:
    """RIFE 帧插值器

    参考 CogVideo 对 RIFE 的集成方式:
    提供统一的帧插值接口，支持多倍插帧。

    注意: 本实现为参考框架，需要安装 RIFE 模型才能使用。
    """

    def __init__(self, config: RIFEInterpConfig):
        self.config = config
        self._model: nn.Module | None = None

    def load_model(self, model_path: str | None = None) -> bool:
        """加载 RIFE 模型

        Args:
            model_path: 模型权重路径

        Returns:
            是否成功加载
        """
        logger.info("RIFE 帧插值模型加载为参考框架，需集成实际 RIFE 实现")
        return True

    def interpolate_pair(
        self,
        frame0: torch.Tensor,
        frame1: torch.Tensor,
        t: float = 0.5,
    ) -> torch.Tensor:
        """在两帧之间插值

        Args:
            frame0: 前帧 [B, C, H, W]
            frame1: 后帧 [B, C, H, W]
            t: 插值时刻 (0=前帧, 1=后帧)

        Returns:
            插值帧 [B, C, H, W]
        """
        if self._model is None:
            # 无模型时使用线性插值
            return (1 - t) * frame0 + t * frame1

        with torch.no_grad():
            mid_frame = self._model(frame0, frame1, t)
        return mid_frame

    def interpolate_video(
        self,
        frames: torch.Tensor,
        factor: int | None = None,
    ) -> torch.Tensor:
        """对视频进行多倍插帧

        Args:
            frames: 输入帧 [B, T, C, H, W]
            factor: 插帧倍数 (默认使用配置值)

        Returns:
            插帧后的帧序列
        """
        if factor is None:
            factor = self.config.interpolation_factor

        B, T, C, H, W = frames.shape
        result_frames = []

        for t in range(T - 1):
            frame0 = frames[:, t]
            frame1 = frames[:, t + 1]
            result_frames.append(frame0)

            # 在两帧之间插入 (factor - 1) 个中间帧
            for i in range(1, factor):
                t_mid = i / factor
                mid_frame = self.interpolate_pair(frame0, frame1, t_mid)
                result_frames.append(mid_frame)

        result_frames.append(frames[:, -1])
        return torch.stack(result_frames, dim=1)


# ---------------------------------------------------------------------------
# 分层退化处理 (STAR inspired) - P2
# ---------------------------------------------------------------------------

class DegradationLevel(Enum):
    """退化级别"""
    LIGHT = "light_deg"    # 轻度退化: 适合质量较好的输入
    HEAVY = "heavy_deg"    # 重度退化: 适合严重退化的输入


@dataclass
class DegradationParams:
    """退化处理参数

    参考 STAR 的分层退化处理:
    根据输入视频的退化程度选择不同的预处理参数，
    light_deg 适用于轻微退化的视频，heavy_deg 适用于严重退化的视频。
    """
    # 退化级别
    level: DegradationLevel = DegradationLevel.LIGHT
    # 降采样倍数 (用于退化模拟)
    downsample_scale: float = 1.0
    # 高斯噪声标准差
    noise_std: float = 0.0
    # JPEG 压缩质量 (1-100)
    jpeg_quality: int = 100
    # 高斯模糊核大小
    blur_kernel_size: int = 1
    # 高斯模糊标准差
    blur_sigma: float = 0.0
    # 运动模糊强度
    motion_blur_strength: float = 0.0
    # 色彩偏移强度
    color_shift: float = 0.0
    # 压缩伪影强度
    compression_artifact: float = 0.0


# STAR 预设退化参数
STAR_DEGRADATION_PRESETS: dict[DegradationLevel, DegradationParams] = {
    DegradationLevel.LIGHT: DegradationParams(
        level=DegradationLevel.LIGHT,
        downsample_scale=2.0,
        noise_std=5.0 / 255.0,
        jpeg_quality=80,
        blur_kernel_size=3,
        blur_sigma=0.5,
        motion_blur_strength=0.0,
        color_shift=0.02,
        compression_artifact=0.1,
    ),
    DegradationLevel.HEAVY: DegradationParams(
        level=DegradationLevel.HEAVY,
        downsample_scale=4.0,
        noise_std=25.0 / 255.0,
        jpeg_quality=30,
        blur_kernel_size=7,
        blur_sigma=2.0,
        motion_blur_strength=0.5,
        color_shift=0.1,
        compression_artifact=0.5,
    ),
}


@dataclass
class HierarchicalDegradationConfig:
    """分层退化处理配置

    参考 STAR 的 light_deg / heavy_deg 退化预设:
    根据输入质量自动或手动选择退化级别，
    对应不同的模型配置和参数设置。
    """
    # 是否启用分层退化处理
    enabled: bool = True
    # 默认退化级别
    default_level: DegradationLevel = DegradationLevel.LIGHT
    # 是否自动检测退化级别
    auto_detect: bool = False
    # 自动检测阈值: MSE 低于此值使用 light_deg
    auto_detect_mse_threshold: float = 0.05
    # 退化预设参数
    presets: dict[DegradationLevel, DegradationParams] = field(
        default_factory=lambda: dict(STAR_DEGRADATION_PRESETS)
    )


class HierarchicalDegradationProcessor:
    """分层退化处理器

    参考 STAR 的 light_deg / heavy_deg 分层退化处理:
    根据输入视频的退化程度选择不同的处理策略和参数。
    """

    def __init__(self, config: HierarchicalDegradationConfig):
        self.config = config

    def detect_degradation_level(
        self,
        frame: torch.Tensor,
    ) -> DegradationLevel:
        """自动检测帧的退化级别

        通过分析帧的质量指标 (噪声水平、模糊程度等)
        判断应使用 light_deg 还是 heavy_deg 级别。

        Args:
            frame: 输入帧 [C, H, W]

        Returns:
            检测到的退化级别
        """
        cfg = self.config

        if not cfg.auto_detect:
            return cfg.default_level

        # 估计噪声水平: 使用局部方差法
        # 将帧转为灰度
        if frame.shape[0] == 3:
            gray = 0.299 * frame[0] + 0.587 * frame[1] + 0.114 * frame[2]
        else:
            gray = frame.mean(dim=0)

        gray = gray.unsqueeze(0).unsqueeze(0)

        # 局部均值和方差
        kernel_size = 7
        local_mean = F.avg_pool2d(gray, kernel_size, stride=1, padding=kernel_size // 2)
        local_var = F.avg_pool2d(gray ** 2, kernel_size, stride=1, padding=kernel_size // 2) - local_mean ** 2
        noise_estimate = local_var.mean().sqrt().item()

        # 根据噪声水平判断退化级别
        if noise_estimate < cfg.auto_detect_mse_threshold:
            logger.debug(f"检测到轻度退化 (噪声: {noise_estimate:.4f})")
            return DegradationLevel.LIGHT
        else:
            logger.debug(f"检测到重度退化 (噪声: {noise_estimate:.4f})")
            return DegradationLevel.HEAVY

    def get_params(self, level: DegradationLevel | None = None) -> DegradationParams:
        """获取指定退化级别的参数

        Args:
            level: 退化级别 (None 使用默认级别)

        Returns:
            退化参数
        """
        if level is None:
            level = self.config.default_level
        return self.config.presets.get(level, STAR_DEGRADATION_PRESETS[level])

    def apply_degradation(
        self,
        frame: torch.Tensor,
        params: DegradationParams | None = None,
    ) -> torch.Tensor:
        """对帧应用退化处理 (用于训练数据增强或退化模拟)

        Args:
            frame: 输入帧 [C, H, W]
            params: 退化参数 (None 使用默认)

        Returns:
            退化后的帧
        """
        if params is None:
            params = self.get_params()

        result = frame.clone()

        # 1. 降采样 + 上采样 (模拟分辨率退化)
        if params.downsample_scale > 1.0:
            C, H, W = result.shape
            result = result.unsqueeze(0)
            result = F.interpolate(
                result,
                scale_factor=1.0 / params.downsample_scale,
                mode="bilinear",
                align_corners=False,
            )
            result = F.interpolate(
                result,
                size=(H, W),
                mode="bilinear",
                align_corners=False,
            )
            result = result.squeeze(0)

        # 2. 高斯噪声
        if params.noise_std > 0:
            noise = torch.randn_like(result) * params.noise_std
            result = result + noise

        # 3. 高斯模糊
        if params.blur_sigma > 0 and params.blur_kernel_size > 1:
            kernel = self._make_gaussian_kernel(params.blur_kernel_size, params.blur_sigma)
            kernel = kernel.to(result.device)
            C = result.shape[0]
            result = result.unsqueeze(0)
            for c in range(C):
                result[:, c:c + 1] = F.conv2d(
                    result[:, c:c + 1],
                    kernel.unsqueeze(0).unsqueeze(0),
                    padding=params.blur_kernel_size // 2,
                )
            result = result.squeeze(0)

        # 4. 色彩偏移
        if params.color_shift > 0:
            shift = torch.randn(3, 1, 1, device=result.device) * params.color_shift
            if result.shape[0] == 3:
                result = result + shift

        # 裁剪到 [0, 1]
        result = result.clamp(0, 1)

        return result

    @staticmethod
    def _make_gaussian_kernel(size: int, sigma: float) -> torch.Tensor:
        """创建高斯模糊核"""
        coords = torch.arange(size, dtype=torch.float32) - size // 2
        g = torch.exp(-coords ** 2 / (2 * sigma ** 2))
        kernel = g.outer(g)
        kernel = kernel / kernel.sum()
        return kernel


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_video_processing_summary() -> dict[str, Any]:
    """获取视频处理增强模块的功能摘要

    Returns:
        包含各功能及其优先级和状态的字典
    """
    return {
        "venhancer_pipeline": {
            "name": "空间+时间+精炼一体化帧插值",
            "source": "VEnhancer",
            "priority": "P1",
            "description": "三阶段协同处理框架，空间超分+时间插帧+精炼后处理",
            "status": "implemented",
        },
        "raft_flow": {
            "name": "RAFT 光流集成",
            "source": "Upscale-A-Video",
            "priority": "P2",
            "description": "帧间运动估计与对齐，支持前向-后向一致性检查",
            "status": "reference",
        },
        "depth_aware_interp": {
            "name": "深度感知帧插值",
            "source": "DAIN",
            "priority": "P3",
            "description": "利用深度信息指导流投影，遮挡区域更准确的插帧",
            "status": "reference",
        },
        "causal_inference": {
            "name": "因果条件推理",
            "source": "Stream-DiffVSR",
            "priority": "P3",
            "description": "仅使用过去帧的在线流式推理框架",
            "status": "reference",
        },
        "frame_analysis": {
            "name": "视频帧分析",
            "source": "Waifu2x-Extension-GUI",
            "priority": "P2",
            "description": "重复帧检测和场景变化识别",
            "status": "implemented",
        },
        "rife_interp": {
            "name": "RIFE 帧插值",
            "source": "CogVideo",
            "priority": "P2",
            "description": "实时中间流估计帧插值参考",
            "status": "reference",
        },
        "hierarchical_degradation": {
            "name": "分层退化处理",
            "source": "STAR",
            "priority": "P2",
            "description": "light_deg/heavy_deg 退化预设参数与自动检测",
            "status": "implemented",
        },
    }
