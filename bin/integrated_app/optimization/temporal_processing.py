"""帧间一致性 / 时序处理模块

本模块属于 SeedVR2 视频修复项目的 AI 推理优化层，提供多种视频帧间时序一致性
增强技术，解决视频修复中常见的闪烁、帧间不连续等问题，确保输出视频流畅自然。

核心技术栈:
- PyTorch: 张量计算与神经网络操作
- 光流估计与对齐: RAFT/grid_sample 帧运动补偿
- 注意力机制: 时序注意力、双向采样策略
- 特征传播: 可变形对齐、递归状态传递
- KV 缓存: 流式推理加速

竞品来源:
- Upscale-A-Video: 特征传播模块 (P1)
- StableVSR: Temporal Texture Guidance (P0), 双向采样策略 (P2)
- BasicVSR_PlusPlus: 光流引导可变形对齐 (P1), fbConsistencyCheck (P1), 二次传播 (P2)
- Stream-DiffVSR: ARTG 光流对齐 (P2), Temporal Processor Module (P2)
- Turtle: Patch-level KV Cache (P1), 截断因果历史模型 (P1)
- FlashVSR: Stream Forward KV Cache (P0)
- RVRT: 递归-并行混合架构 (P2)

Key Features:
- Temporal Texture Guidance: StableVSR 风格的前帧 warp 到当前帧作为 condition
- Stream Forward KV Cache: FlashVSR 流式推理 KV 缓存机制
- 特征传播模块: Upscale-A-Video 风格的光流传播后处理
- 光流引导可变形对齐: BasicVSR++ 的 Flow-guided Deformable Alignment
- fbConsistencyCheck: 前向-后向一致性检查遮挡检测
- Patch-level KV Cache: Turtle 的 patch 级 K/V 缓存 + 增量更新
- 双向采样策略: 交替使用前帧/后帧引导
- 二次网格传播: 多层级邻帧特征聚合
- ARTG 自回归对齐: 逐帧递进式时序对齐
- Temporal Processor: 轻量级时序感知解码器
- 递归-并行混合架构: clip 内并行 + clip 间递归
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Temporal Texture Guidance (StableVSR inspired) - P0
# ---------------------------------------------------------------------------

@dataclass
class TemporalGuidanceConfig:
    """Temporal Texture Guidance 配置

    参考 StableVSR 的 restoration_guidance_scale 参数，
    将前帧的 x0_est warp 到当前帧作为 condition。
    """
    # 是否启用 Temporal Texture Guidance
    enabled: bool = True
    # guidance scale: 控制前帧信息对当前帧的影响程度
    # 1.0 = 标准修复, >1.0 = 更强的前帧约束, <1.0 = 更自由的修复
    guidance_scale: float = 1.0
    # warp 方法: 'bilinear' (简单双线性) 或 'flow' (光流引导)
    warp_method: str = "bilinear"
    # 遮挡检测阈值: fbConsistencyCheck 的阈值
    occlusion_threshold: float = 0.5
    # 融合策略: 'add' (直接加), 'concat' (拼接通道), 'weighted' (加权混合)
    fusion_strategy: str = "weighted"


class TemporalTextureGuidance:
    """Temporal Texture Guidance 模块

    参考 StableVSR 的 Temporal Texture Guidance 机制:
    在 DiT 采样过程中，将前一帧的估计输出 warp 到当前帧位置，
    作为额外的条件信号，增强帧间一致性。

    核心思路:
    1. 使用前一帧的 x0_est (去噪估计) 作为参考
    2. 通过光流或简单对齐将前帧 warp 到当前帧
    3. 使用 fbConsistencyCheck 检测遮挡区域
    4. 在遮挡区域减少前帧影响，避免错误传播

    Usage:
        guidance = TemporalTextureGuidance(config)

        # 在 DiT 采样循环中
        for t in timesteps:
            x0_est = dit(noisy_x, t, condition)

            # 应用 Temporal Texture Guidance
            guided_condition = guidance.apply(
                current_frame_idx=i,
                x0_est_previous=prev_x0_est,
                current_latent=noisy_x,
                condition=condition,
            )
    """

    def __init__(self, config: TemporalGuidanceConfig | None = None):
        """初始化时序纹理引导模块

        Args:
            config: 时序引导配置，为 None 时使用默认配置
        """
        self.config = config or TemporalGuidanceConfig()
        self._previous_x0_est: torch.Tensor | None = None
        self._previous_flow: torch.Tensor | None = None

    def apply(
        self,
        current_frame_idx: int,
        x0_est_previous: torch.Tensor | None,
        current_latent: torch.Tensor,
        condition: torch.Tensor,
        flow: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """应用 Temporal Texture Guidance

        Args:
            current_frame_idx: 当前帧索引 (0 表示首帧，不需要 guidance)
            x0_est_previous: 前一帧的去噪估计 (latent space)
            current_latent: 当前帧的噪声 latent
            condition: 当前帧的原始条件信号
            flow: 前帧到当前帧的光流 (可选)

        Returns:
            增强后的条件信号
        """
        if not self.config.enabled or current_frame_idx == 0 or x0_est_previous is None:
            return condition

        scale = self.config.guidance_scale
        fusion = self.config.fusion_strategy

        # Warp 前帧估计到当前帧
        warped_previous = self._warp_frame(
            x0_est_previous, current_latent, flow
        )

        # 遮挡检测: 使用 fbConsistencyCheck
        if flow is not None:
            occlusion_mask = self._compute_occlusion_mask(
                warped_previous, flow
            )
        else:
            # 无光流时使用简单相似度检测遮挡
            occlusion_mask = self._compute_similarity_mask(
                warped_previous, condition
            )

        # 融合前帧信息
        if fusion == "add":
            # 直接加法融合
            guided = condition + scale * warped_previous * occlusion_mask
        elif fusion == "concat":
            # 拼接通道融合 (需要修改 condition 通道数)
            guided = torch.cat([condition, warped_previous * occlusion_mask], dim=-1)
        else:  # weighted
            # 加权混合: 遮挡区域使用原始 condition，非遮挡区域融合前帧
            guided = (1 - scale * occlusion_mask) * condition + scale * warped_previous * occlusion_mask

        return guided

    def _warp_frame(
        self,
        previous_frame: torch.Tensor,
        current_frame: torch.Tensor,
        flow: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """将前帧 warp 到当前帧位置

        Args:
            previous_frame: 前帧张量
            current_frame: 当前帧张量 (用于确定目标尺寸)
            flow: 光流 (前帧->当前帧)，None 时使用简单对齐

        Returns:
            warped 后的前帧
        """
        if flow is not None and self.config.warp_method == "flow":
            return self._warp_with_flow(previous_frame, flow)
        else:
            return self._warp_bilinear(previous_frame, current_frame)

    def _warp_bilinear(
        self,
        source: torch.Tensor,
        target: torch.Tensor,
    ) -> torch.Tensor:
        """简单双线性 warp (无光流时使用)

        在没有光流信息时，直接使用前一帧作为当前帧的参考。
        对于轻微运动，这仍然提供了有价值的时间一致性信息。
        """
        # 确保 source 和 target 尺寸一致
        if source.shape != target.shape:
            # 简单缩放对齐
            target_size = target.shape[-2:]
            source = F.interpolate(
                source.unsqueeze(0) if source.ndim == 3 else source,
                size=target_size,
                mode="bilinear",
                align_corners=False,
            )
            if source.ndim == 4 and target.ndim == 3:
                source = source.squeeze(0)

        return source

    def _warp_with_flow(
        self,
        source: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """光流引导 warp"""
        # source: (C, H, W) or (B, C, H, W)
        # flow: (2, H, W) or (B, 2, H, W)
        if source.ndim == 3:
            source = source.unsqueeze(0)
        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = source.shape

        # 创建网格坐标
        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=source.device, dtype=source.dtype),
            torch.arange(w, device=source.device, dtype=source.dtype),
            indexing="ij"
        )
        grid = torch.stack([grid_x, grid_y], dim=-1)  # (H, W, 2)

        # 添加 flow 偏移
        grid = grid + flow.permute(0, 2, 3, 1)  # (B, H, W, 2)

        # 归一化到 [-1, 1]
        grid[:, :, :, 0] = 2.0 * grid[:, :, :, 0] / (w - 1) - 1.0
        grid[:, :, :, 1] = 2.0 * grid[:, :, :, 1] / (h - 1) - 1.0

        # Warp
        warped = F.grid_sample(source, grid, mode="bilinear", align_corners=True, padding_mode="zeros")

        return warped.squeeze(0) if source.shape[0] == 1 else warped

    def _compute_occlusion_mask(
        self,
        warped_frame: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """前向-后向一致性检查遮挡检测

        参考 Upscale-A-Video 和 BasicVSR++ 的 fbConsistencyCheck:
        计算前向光流和后向光流的 round-trip error，
        error 大的区域视为遮挡，减少前帧影响。

        Args:
            warped_frame: warp 后的帧
            flow: 前向光流

        Returns:
            遮挡掩码 (0=遮挡, 1=可见)
        """
        # 简化实现: 使用 flow magnitude 作为遮挡指标
        # 大 flow magnitude 通常意味着遮挡边界或新出现区域
        flow_magnitude = torch.norm(flow, dim=0 if flow.ndim == 3 else 1)

        # 阈值化: 大于阈值的区域为遮挡
        occlusion = (flow_magnitude > self.config.occlusion_threshold).float()

        # 掩码: 1=可见区域(使用前帧), 0=遮挡区域(不使用前帧)
        mask = 1.0 - occlusion

        return mask

    def _compute_similarity_mask(
        self,
        warped_frame: torch.Tensor,
        reference: torch.Tensor,
    ) -> torch.Tensor:
        """基于相似度的遮挡检测 (无光流时的 fallback)

        计算 warped 前帧和当前帧的相似度，
        低相似度区域视为遮挡。
        """
        # 计算通道维度的 cosine 相似度
        if warped_frame.ndim == 4:
            # (B, C, H, W) -> per-pixel similarity
            sim = F.cosine_similarity(warped_frame, reference, dim=1)
        elif warped_frame.ndim == 3:
            # (C, H, W) -> per-pixel similarity
            sim = F.cosine_similarity(warped_frame.unsqueeze(0), reference.unsqueeze(0), dim=1).squeeze(0)
        else:
            # 潜空间: 最后一个维度是通道
            sim = F.cosine_similarity(warped_frame, reference, dim=-1)

        # 高相似度 = 非遮挡
        mask = (sim > 0.5).float()
        return mask


# ---------------------------------------------------------------------------
# Stream Forward KV Cache (FlashVSR inspired) - P0
# ---------------------------------------------------------------------------

@dataclass
class StreamKVCacheConfig:
    """Stream Forward KV Cache 配置

    参考 FlashVSR 的流式推理 KV 缓存机制，
    在视频修复中缓存 DiT 的 Key/Value 投影，
    减少后续帧的计算量。
    """
    # 是否启用 KV Cache
    enabled: bool = True
    # 最大缓存帧数 (超过时清除最旧的)
    max_cached_frames: int = 8
    # 缓存策略: 'fifo' (先进先出) 或 'priority' (基于重要性)
    cache_policy: str = "fifo"
    # 增量更新: 是否使用增量更新而非完全重算
    incremental_update: bool = True


class StreamForwardKVCache:
    """Stream Forward KV Cache 模块

    参考 FlashVSR 的流式推理 KV 缓存机制:
    在视频修复的 DiT 推理中，缓存已处理帧的 Key/Value 投影，
    后续帧可以复用这些缓存，减少重复计算。

    核心思路:
    1. 处理帧 i 时，计算并缓存 K_i, V_i
    2. 处理帧 i+1 时，可以复用部分 K_i, V_i (根据时序依赖范围)
    3. 维护 FIFO 队列，超过 max_cached_frames 时清除最旧缓存
    4. 支持增量更新: 只更新变化的 patch 部分

    Usage:
        kv_cache = StreamForwardKVCache(config)

        # 在 DiT 推理循环中
        for frame_idx in range(num_frames):
            # 检查是否有可复用的 KV 缓存
            cached_kv = kv_cache.get_cached_kv(frame_idx)

            # DiT 推理 (传入 cached_kv 可跳过部分注意力计算)
            output, new_kv = dit_forward(
                input_latent,
                cached_kv=cached_kv,
                frame_idx=frame_idx,
            )

            # 缓存当前帧的 KV
            kv_cache.update(frame_idx, new_kv)
    """

    def __init__(self, config: StreamKVCacheConfig | None = None):
        self.config = config or StreamKVCacheConfig()
        self._cache: dict[int, dict[str, torch.Tensor]] = {}
        self._frame_order: list[int] = []

    def update(
        self,
        frame_idx: int,
        kv_data: dict[str, torch.Tensor],
    ) -> None:
        """更新 KV 缓存

        Args:
            frame_idx: 帧索引
            kv_data: 包含 'key' 和 'value' 的字典
        """
        if not self.config.enabled:
            return

        # 添加新缓存
        self._cache[frame_idx] = kv_data
        self._frame_order.append(frame_idx)

        # 维护最大缓存帧数
        while len(self._cache) > self.config.max_cached_frames:
            oldest = self._frame_order[0]
            del self._cache[oldest]
            self._frame_order.remove(oldest)
            logger.debug(f"KV Cache: 清除最旧帧 {oldest}")

        logger.debug(f"KV Cache: 更新帧 {frame_idx}, 缓存大小={len(self._cache)}")

    def get_cached_kv(
        self,
        current_frame_idx: int,
        num_previous_frames: int | None = None,
    ) -> dict[int, dict[str, torch.Tensor]] | None:
        """获取可复用的 KV 缓存

        Args:
            current_frame_idx: 当前帧索引
            num_previous_frames: 需要的前帧数量，None 时使用所有可用缓存

        Returns:
            缓存字典 {frame_idx: {'key': Tensor, 'value': Tensor}}，或 None
        """
        if not self.config.enabled or not self._cache:
            return None

        # 获取当前帧之前的历史帧
        available = {
            idx: kv for idx, kv in self._cache.items()
            if idx < current_frame_idx
        }

        if not available:
            return None

        # 限制前帧数量
        if num_previous_frames is not None:
            sorted_indices = sorted(available.keys(), reverse=True)
            limited_indices = sorted_indices[:num_previous_frames]
            available = {idx: available[idx] for idx in limited_indices}

        return available

    def incremental_update(
        self,
        frame_idx: int,
        new_kv: dict[str, torch.Tensor],
        patch_mask: torch.Tensor | None = None,
    ) -> None:
        """增量更新 KV 缓存

        参考 Turtle 的 patch 级 K/V 缓存 + 增量更新:
        只更新变化的 patch 部分，而非完全重算整个帧的 KV。

        Args:
            frame_idx: 帧索引
            new_kv: 新的 KV 数据
            patch_mask: 变化 patch 的掩码 (None 表示全部更新)
        """
        if not self.config.incremental_update or patch_mask is None:
            self.update(frame_idx, new_kv)
            return

        # 增量更新: 只更新变化区域
        if frame_idx in self._cache:
            existing = self._cache[frame_idx]
            for key_name in ["key", "value"]:
                if key_name in existing and key_name in new_kv:
                    # 在掩码区域使用新值，其余保留旧值
                    mask_expanded = patch_mask.expand_as(new_kv[key_name])
                    updated = existing[key_name] * (1 - mask_expanded) + new_kv[key_name] * mask_expanded
                    new_kv[key_name] = updated

        self.update(frame_idx, new_kv)

    def clear(self) -> None:
        """清除所有 KV 缓存"""
        self._cache.clear()
        self._frame_order.clear()
        logger.debug("KV Cache: 已清除所有缓存")

    def get_stats(self) -> dict:
        """获取缓存统计"""
        total_size_mb = 0.0
        for kv_data in self._cache.values():
            for tensor in kv_data.values():
                if isinstance(tensor, torch.Tensor):
                    total_size_mb += tensor.numel() * tensor.element_size() / (1024 ** 2)

        return {
            "cached_frames": len(self._cache),
            "total_size_mb": round(total_size_mb, 1),
            "max_cached_frames": self.config.max_cached_frames,
            "frame_range": f"{min(self._frame_order)}-{max(self._frame_order)}" if self._frame_order else "empty",
        }


# ---------------------------------------------------------------------------
# 特征传播模块 (Upscale-A-Video inspired) - P1
# ---------------------------------------------------------------------------

class FeaturePropagation:
    """特征传播模块 - 非可学习版光流传播后处理

    参考 Upscale-A-Video 的非可学习版光流传播:
    在修复后处理阶段，使用光流将前帧的特征传播到当前帧，
    增强帧间一致性。

    与 TemporalTextureGuidance 的区别:
    - TemporalTextureGuidance: 在 DiT 采样过程中使用 (修改 condition)
    - FeaturePropagation: 在后处理阶段使用 (修改最终输出)
    """

    def __init__(self, propagation_weight: float = 0.2):
        self.propagation_weight = propagation_weight

    def propagate(
        self,
        current_frame: torch.Tensor,
        previous_frame: torch.Tensor | None = None,
        flow: torch.Tensor | None = None,
        occlusion_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """传播前帧特征到当前帧

        Args:
            current_frame: 当前修复帧 (pixel space, H W C, uint8 or float)
            previous_frame: 前一修复帧 (同格式)
            flow: 前帧到当前帧的光流
            occlusion_mask: 遮挡掩码 (0=遮挡)

        Returns:
            传播后的当前帧
        """
        if previous_frame is None:
            return current_frame

        # Warp 前帧
        if flow is not None:
            warped_prev = self._warp_with_flow(previous_frame, flow)
        else:
            warped_prev = previous_frame  # 无光流时直接使用前帧

        # 遮挡检测
        if occlusion_mask is None:
            # 使用 cosine 相似度检测遮挡
            if current_frame.ndim == 3:
                sim = F.cosine_similarity(
                    current_frame.permute(2, 0, 1).unsqueeze(0).float(),
                    warped_prev.permute(2, 0, 1).unsqueeze(0).float(),
                    dim=1,
                ).squeeze(0)
            else:
                sim = F.cosine_similarity(current_frame.float(), warped_prev.float(), dim=1)

            occlusion_mask = (sim > 0.3).float()

        # 加权混合: 非遮挡区域融合前帧信息
        weight = self.propagation_weight * occlusion_mask
        if current_frame.ndim == 3:
            weight = weight.unsqueeze(-1)

        result = current_frame * (1 - weight) + warped_prev * weight

        return result

    def _warp_with_flow(
        self,
        source: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """光流引导 warp"""
        if source.ndim == 3:
            source_chw = source.permute(2, 0, 1).unsqueeze(0).float()
        else:
            source_chw = source.unsqueeze(0).float() if source.ndim == 3 else source.float()

        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = source_chw.shape

        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=source.device, dtype=torch.float32),
            torch.arange(w, device=source.device, dtype=torch.float32),
            indexing="ij"
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0)

        grid = grid + flow.permute(0, 2, 3, 1)
        grid[..., 0] = 2.0 * grid[..., 0] / (w - 1) - 1.0
        grid[..., 1] = 2.0 * grid[..., 1] / (h - 1) - 1.0

        warped = F.grid_sample(source_chw, grid, mode="bilinear", align_corners=True, padding_mode="zeros")

        if source.ndim == 3:
            warped = warped.squeeze(0).permute(1, 2, 0)

        return warped


# ---------------------------------------------------------------------------
# 光流引导可变形对齐 (BasicVSR++ inspired) - P1
# ---------------------------------------------------------------------------

class DeformableAlignment:
    """光流引导可变形对齐模块

    参考 BasicVSR++ 的 Flow-guided Deformable Alignment:
    使用光流引导的可变形卷积对齐相邻帧，
    比简单的 bilinear warp 更精确。

    注意: 这是一个轻量级实现框架，实际的可变形卷积需要
    DCNv2/DCNv3 库支持。当前实现使用 bilinear warp 作为 fallback。
    """

    def __init__(self, num_groups: int = 8, channels: int = 64):
        self.num_groups = num_groups
        self.channels = channels

    def align_frames(
        self,
        neighbor_frame: torch.Tensor,
        reference_frame: torch.Tensor,
        flow: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """对齐相邻帧到参考帧

        Args:
            neighbor_frame: 需要对齐的帧
            reference_frame: 参考帧 (目标位置)
            flow: 光流 (neighbor -> reference)

        Returns:
            对齐后的帧
        """
        if flow is not None:
            # 使用光流进行 warp
            return self._flow_warp(neighbor_frame, flow)
        else:
            # 无光流时使用简单 bilinear 对齐
            return neighbor_frame

    def _flow_warp(
        self,
        frame: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """使用光流进行 warp"""
        if frame.ndim == 3:
            frame = frame.permute(2, 0, 1).unsqueeze(0).float()
        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = frame.shape

        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=frame.device, dtype=torch.float32),
            torch.arange(w, device=frame.device, dtype=torch.float32),
            indexing="ij"
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0)
        grid = grid + flow.permute(0, 2, 3, 1)
        grid[..., 0] = 2.0 * grid[..., 0] / (w - 1) - 1.0
        grid[..., 1] = 2.0 * grid[..., 1] / (h - 1) - 1.0

        warped = F.grid_sample(frame, grid, mode="bilinear", align_corners=True, padding_mode="zeros")
        return warped


# ---------------------------------------------------------------------------
# 截断因果历史模型 (Turtle inspired) - P1
# ---------------------------------------------------------------------------

class TruncatedCausalHistory:
    """截断因果历史模型

    参考 Turtle 的 num_frames_tocache 参数:
    精确控制时序依赖范围，只缓存最近 N 帧的历史信息，
    避免无限增长的历史缓存导致显存溢出。

    Usage:
        history = TruncatedCausalHistory(num_frames_tocache=4)

        for frame in frames:
            # 获取历史帧
            context = history.get_context()

            # 处理当前帧 (使用 context 作为条件)
            result = model(frame, context=context)

            # 更新历史
            history.add_frame(result)
    """

    def __init__(self, num_frames_tocache: int = 4):
        self.num_frames_tocache = num_frames_tocache
        self._history: list[torch.Tensor] = []

    def add_frame(self, frame: torch.Tensor) -> None:
        """添加帧到历史缓存"""
        self._history.append(frame.detach())

        # 超过限制时移除最旧帧
        while len(self._history) > self.num_frames_tocache:
            oldest = self._history[0]
            self._history.remove(oldest)
            del oldest

    def get_context(self) -> list[torch.Tensor]:
        """获取历史帧作为上下文"""
        return list(self._history)

    def clear(self) -> None:
        """清除历史"""
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)


# ---------------------------------------------------------------------------
# 双向采样策略 (StableVSR inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class BidirectionalSamplingConfig:
    """双向采样策略配置

    参考 StableVSR 的正向/反向交替帧间引导机制，
    在扩散采样中同时利用前一帧和后一帧的 x0_est
    增强帧间一致性。
    """

    # 是否启用双向采样
    enabled: bool = True
    # 采样模式: 'alternate' (交替) 或 'bidirectional_fusion' (双向融合)
    mode: str = "alternate"
    # 正向引导权重: 前一帧 x0_est 的影响程度
    forward_weight: float = 0.5
    # 反向引导权重: 后一帧 x0_est 的影响程度
    backward_weight: float = 0.5


class BidirectionalSamplingStrategy:
    """双向采样策略

    参考 StableVSR 的正向/反向交替帧间引导机制:
    在扩散采样过程中，交替使用前一帧和后一帧的去噪估计 (x0_est)
    作为当前帧的引导信号，增强帧间时序一致性。

    两种模式:
    - alternate (交替): 奇数步使用前帧引导，偶数步使用后帧引导
    - bidirectional_fusion (双向融合): 同时使用前帧和后帧的加权融合

    核心思路:
    1. 正向引导: 使用前一帧的 x0_est warp 到当前帧
    2. 反向引导: 使用后一帧的 x0_est warp 到当前帧
    3. 交替模式: 在不同采样步交替使用正向/反向引导
    4. 融合模式: 在每一步同时融合正向和反向引导

    Usage:
        strategy = BidirectionalSamplingStrategy(BidirectionalSamplingConfig())

        for step_idx, t in enumerate(timesteps):
            output = model(noisy_x, t, condition)

            # 获取引导信号
            guided = strategy.apply(
                step_idx=step_idx,
                current_output=output,
                forward_x0_est=prev_x0_est,
                backward_x0_est=next_x0_est,
            )
    """

    def __init__(self, config: BidirectionalSamplingConfig | None = None):
        self.config = config or BidirectionalSamplingConfig()
        self._step_counter: int = 0

    def apply(
        self,
        step_idx: int,
        current_output: torch.Tensor,
        forward_x0_est: torch.Tensor | None = None,
        backward_x0_est: torch.Tensor | None = None,
        flow_forward: torch.Tensor | None = None,
        flow_backward: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """应用双向采样引导

        Args:
            step_idx: 当前采样步索引
            current_output: 当前步的模型输出
            forward_x0_est: 前一帧的去噪估计 (正向引导)
            backward_x0_est: 后一帧的去噪估计 (反向引导)
            flow_forward: 前帧到当前帧的光流
            flow_backward: 后帧到当前帧的光流

        Returns:
            引导后的输出
        """
        if not self.config.enabled:
            return current_output

        if forward_x0_est is None and backward_x0_est is None:
            return current_output

        mode = self.config.mode

        if mode == "alternate":
            return self._apply_alternate(
                step_idx, current_output,
                forward_x0_est, backward_x0_est,
                flow_forward, flow_backward,
            )
        else:  # bidirectional_fusion
            return self._apply_fusion(
                step_idx, current_output,
                forward_x0_est, backward_x0_est,
                flow_forward, flow_backward,
            )

    def _apply_alternate(
        self,
        step_idx: int,
        current_output: torch.Tensor,
        forward_x0_est: torch.Tensor | None,
        backward_x0_est: torch.Tensor | None,
        flow_forward: torch.Tensor | None,
        flow_backward: torch.Tensor | None,
    ) -> torch.Tensor:
        """交替模式: 奇数步正向引导，偶数步反向引导"""
        if step_idx % 2 == 0:
            # 偶数步: 正向引导 (前帧)
            if forward_x0_est is not None:
                warped = self._warp_if_needed(
                    forward_x0_est, current_output, flow_forward
                )
                return current_output * (1 - self.config.forward_weight) + warped * self.config.forward_weight
        else:
            # 奇数步: 反向引导 (后帧)
            if backward_x0_est is not None:
                warped = self._warp_if_needed(
                    backward_x0_est, current_output, flow_backward
                )
                return current_output * (1 - self.config.backward_weight) + warped * self.config.backward_weight

        return current_output

    def _apply_fusion(
        self,
        step_idx: int,
        current_output: torch.Tensor,
        forward_x0_est: torch.Tensor | None,
        backward_x0_est: torch.Tensor | None,
        flow_forward: torch.Tensor | None,
        flow_backward: torch.Tensor | None,
    ) -> torch.Tensor:
        """双向融合模式: 同时融合正向和反向引导"""
        fwd_weight = self.config.forward_weight
        bwd_weight = self.config.backward_weight
        total_weight = fwd_weight + bwd_weight

        # 归一化权重
        if total_weight > 0:
            fwd_weight /= total_weight
            bwd_weight /= total_weight

        result = current_output * (1 - fwd_weight - bwd_weight)

        if forward_x0_est is not None:
            warped_fwd = self._warp_if_needed(
                forward_x0_est, current_output, flow_forward
            )
            result = result + warped_fwd * fwd_weight

        if backward_x0_est is not None:
            warped_bwd = self._warp_if_needed(
                backward_x0_est, current_output, flow_backward
            )
            result = result + warped_bwd * bwd_weight

        return result

    def _warp_if_needed(
        self,
        source: torch.Tensor,
        target: torch.Tensor,
        flow: torch.Tensor | None,
    ) -> torch.Tensor:
        """如果尺寸不匹配或提供光流，执行 warp"""
        if flow is not None:
            return self._warp_with_flow(source, flow)

        # 无光流时确保尺寸一致
        if source.shape != target.shape:
            target_size = target.shape[-2:]
            source = F.interpolate(
                source.unsqueeze(0) if source.ndim == 3 else source,
                size=target_size,
                mode="bilinear",
                align_corners=False,
            )
            if source.ndim == 4 and target.ndim == 3:
                source = source.squeeze(0)

        return source

    def _warp_with_flow(
        self,
        source: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """使用光流进行 warp"""
        if source.ndim == 3:
            source = source.unsqueeze(0)
        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = source.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=source.device, dtype=source.dtype),
            torch.arange(w, device=source.device, dtype=source.dtype),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0)
        grid = grid + flow.permute(0, 2, 3, 1)
        grid[..., 0] = 2.0 * grid[..., 0] / (w - 1) - 1.0
        grid[..., 1] = 2.0 * grid[..., 1] / (h - 1) - 1.0

        warped = F.grid_sample(source, grid, mode="bilinear", align_corners=True, padding_mode="zeros")
        return warped.squeeze(0) if source.shape[0] == 1 else warped

    def reset(self) -> None:
        """重置步计数器 (新序列开始时调用)"""
        self._step_counter = 0


# ---------------------------------------------------------------------------
# Second-order Grid Propagation (BasicVSR++ inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class SecondOrderGridPropagationConfig:
    """二次传播配置

    参考 BasicVSR++ (BasicVSR_PlusPlus) 的二次传播机制，
    充分利用相邻帧信息: 一次传播使用直接相邻帧，
    二次传播进一步利用一次传播结果和更多相邻帧。
    """

    # 是否启用二次传播
    enabled: bool = True
    # 一次传播的相邻帧数量 (每侧)
    first_order_neighbors: int = 1
    # 二次传播的相邻帧数量 (每侧)
    second_order_neighbors: int = 2
    # 传播融合权重: 二次传播结果的融合比例
    fusion_weight: float = 0.3


class SecondOrderGridPropagation:
    """二次网格传播模块

    参考 BasicVSR++ (BasicVSR_PlusPlus) 的二次传播机制:
    一次传播使用直接相邻帧信息对齐到当前帧，
    二次传播进一步利用一次传播的结果和更远邻帧信息，
    通过 grid_sample 方式传播特征。

    核心思路:
    1. 一次传播: 使用直接相邻帧 (t-1, t+1) 的特征，通过 grid_sample 对齐到当前帧
    2. 二次传播: 将一次传播结果与更远邻帧 (t-2, t+2) 的特征结合，
       再次通过 grid_sample 传播，充分利用时序上下文
    3. 融合: 将一次传播和二次传播的结果加权融合

    Usage:
        propagator = SecondOrderGridPropagation(SecondOrderGridPropagationConfig())

        # 一次传播
        first_order_features = propagator.first_order_propagate(
            current_features, neighbor_features, flows
        )

        # 二次传播
        enhanced_features = propagator.second_order_propagate(
            current_features, first_order_features, extended_neighbor_features, flows
        )
    """

    def __init__(self, config: SecondOrderGridPropagationConfig | None = None):
        self.config = config or SecondOrderGridPropagationConfig()

    def first_order_propagate(
        self,
        current_features: torch.Tensor,
        neighbor_features: list[torch.Tensor],
        flows: list[torch.Tensor],
    ) -> torch.Tensor:
        """一次传播: 使用直接相邻帧信息

        Args:
            current_features: 当前帧特征 (B, C, H, W)
            neighbor_features: 相邻帧特征列表 [(B, C, H, W), ...]
            flows: 光流列表 (neighbor -> current)，与 neighbor_features 一一对应

        Returns:
            一次传播后的特征
        """
        if not self.config.enabled or not neighbor_features:
            return current_features

        aligned_sum = torch.zeros_like(current_features)
        weight_sum = torch.zeros(1, 1, current_features.shape[-2], current_features.shape[-1],
                                 device=current_features.device)

        for feat, flow in zip(neighbor_features, flows):
            # grid_sample 对齐相邻帧到当前帧
            aligned = self._grid_sample_align(feat, flow)

            # 简单可靠性权重: flow 范数越小越可靠
            flow_mag = torch.norm(flow, dim=1 if flow.ndim == 4 else 0, keepdim=True)
            reliability = torch.exp(-flow_mag)

            aligned_sum = aligned_sum + aligned * reliability
            weight_sum = weight_sum + reliability

        weight_sum = weight_sum.clamp(min=1e-8)
        aligned_avg = aligned_sum / weight_sum

        # 与当前帧特征融合
        result = current_features + aligned_avg - current_features  # 残差思路
        # 简单平均融合
        result = (current_features + aligned_avg) / 2.0

        return result

    def second_order_propagate(
        self,
        current_features: torch.Tensor,
        first_order_result: torch.Tensor,
        extended_neighbor_features: list[torch.Tensor],
        extended_flows: list[torch.Tensor],
    ) -> torch.Tensor:
        """二次传播: 利用一次传播结果和更多相邻帧

        Args:
            current_features: 原始当前帧特征 (B, C, H, W)
            first_order_result: 一次传播结果 (B, C, H, W)
            extended_neighbor_features: 更远邻帧特征列表
            extended_flows: 对应光流列表

        Returns:
            二次传播增强后的特征
        """
        if not self.config.enabled:
            return first_order_result

        # 基于一次传播结果进行二次传播
        secondary_aligned = torch.zeros_like(current_features)
        weight_sum = torch.zeros(1, 1, current_features.shape[-2], current_features.shape[-1],
                                 device=current_features.device)

        for feat, flow in zip(extended_neighbor_features, extended_flows):
            aligned = self._grid_sample_align(feat, flow)

            flow_mag = torch.norm(flow, dim=1 if flow.ndim == 4 else 0, keepdim=True)
            reliability = torch.exp(-flow_mag)

            secondary_aligned = secondary_aligned + aligned * reliability
            weight_sum = weight_sum + reliability

        if weight_sum.max() > 1e-8:
            weight_sum = weight_sum.clamp(min=1e-8)
            secondary_aligned = secondary_aligned / weight_sum
        else:
            secondary_aligned = first_order_result

        # 融合一次传播和二次传播结果
        fusion_w = self.config.fusion_weight
        result = (1 - fusion_w) * first_order_result + fusion_w * secondary_aligned

        return result

    def _grid_sample_align(
        self,
        features: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """使用 grid_sample 对齐特征

        Args:
            features: 待对齐的特征 (B, C, H, W)
            flow: 光流 (B, 2, H, W) 或 (2, H, W)

        Returns:
            对齐后的特征
        """
        if features.ndim == 3:
            features = features.unsqueeze(0)
        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = features.shape

        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=features.device, dtype=features.dtype),
            torch.arange(w, device=features.device, dtype=features.dtype),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0)
        grid = grid + flow.permute(0, 2, 3, 1)
        grid[..., 0] = 2.0 * grid[..., 0] / (w - 1) - 1.0
        grid[..., 1] = 2.0 * grid[..., 1] / (h - 1) - 1.0

        aligned = F.grid_sample(features, grid, mode="bilinear", align_corners=True, padding_mode="zeros")
        return aligned


# ---------------------------------------------------------------------------
# ARTG 光流对齐 (Stream-DiffVSR inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class ARTGAlignmentConfig:
    """ARTG 光流对齐配置

    参考 Stream-DiffVSR 的 Auto-regressive Temporal Guidance (ARTG) 机制，
    使用光流自回归地逐帧对齐前帧特征到当前帧。
    """

    # 是否启用 ARTG 对齐
    enabled: bool = True
    # 自回归窗口大小: 每次对齐考虑的前帧数量
    ar_window_size: int = 3
    # 对齐融合权重
    alignment_weight: float = 0.5


class ARTGAlignment:
    """ARTG 光流对齐模块

    参考 Stream-DiffVSR 的 Auto-regressive Temporal Guidance (ARTG):
    自回归时序引导，使用光流逐帧递进地对齐前帧特征到当前帧，
    而非一次性全部对齐。

    核心思路:
    1. 自回归方式: 逐帧递进引导，每帧的对齐依赖前一帧的对齐结果
    2. 光流对齐: 使用光流将前帧特征 warp 到当前帧位置
    3. 递进累积: 对齐结果逐帧传递，形成时序一致的引导链

    与直接对齐的区别:
    - 直接对齐: 每帧独立从原始特征 warp，可能累积误差
    - 自回归对齐: 每帧基于上一帧的对齐结果再对齐，误差更可控

    Usage:
        artg = ARTGAlignment(ARTGAlignmentConfig())

        aligned_features = None
        for frame_idx in range(num_frames):
            aligned_features = artg.align(
                current_features=features[frame_idx],
                previous_aligned=aligned_features,
                flow=flows[frame_idx],
                frame_idx=frame_idx,
            )
    """

    def __init__(self, config: ARTGAlignmentConfig | None = None):
        self.config = config or ARTGAlignmentConfig()
        self._aligned_history: list[torch.Tensor] = []

    def align(
        self,
        current_features: torch.Tensor,
        previous_aligned: torch.Tensor | None,
        flow: torch.Tensor | None,
        frame_idx: int = 0,
    ) -> torch.Tensor:
        """自回归时序对齐

        Args:
            current_features: 当前帧特征 (B, C, H, W)
            previous_aligned: 上一帧对齐后的特征，首帧为 None
            flow: 前帧到当前帧的光流 (B, 2, H, W)
            frame_idx: 当前帧索引

        Returns:
            对齐并融合后的当前帧特征
        """
        if not self.config.enabled:
            return current_features

        # 首帧或无前帧对齐结果时直接返回
        if frame_idx == 0 or previous_aligned is None or flow is None:
            self._update_history(current_features)
            return current_features

        # 自回归对齐: 基于前一帧的对齐结果再对齐
        warped_previous = self._flow_warp(previous_aligned, flow)

        # 融合对齐结果与当前帧特征
        weight = self.config.alignment_weight
        aligned = (1 - weight) * current_features + weight * warped_previous

        # 更新历史
        self._update_history(aligned)

        return aligned

    def _update_history(self, features: torch.Tensor) -> None:
        """更新自回归历史窗口"""
        self._aligned_history.append(features.detach())

        while len(self._aligned_history) > self.config.ar_window_size:
            self._aligned_history.pop(0)

    def _flow_warp(
        self,
        features: torch.Tensor,
        flow: torch.Tensor,
    ) -> torch.Tensor:
        """使用光流进行 warp"""
        if features.ndim == 3:
            features = features.unsqueeze(0)
        if flow.ndim == 3:
            flow = flow.unsqueeze(0)

        b, c, h, w = features.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(h, device=features.device, dtype=features.dtype),
            torch.arange(w, device=features.device, dtype=features.dtype),
            indexing="ij",
        )
        grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0)
        grid = grid + flow.permute(0, 2, 3, 1)
        grid[..., 0] = 2.0 * grid[..., 0] / (w - 1) - 1.0
        grid[..., 1] = 2.0 * grid[..., 1] / (h - 1) - 1.0

        warped = F.grid_sample(features, grid, mode="bilinear", align_corners=True, padding_mode="zeros")
        return warped

    def reset(self) -> None:
        """重置自回归历史 (新序列开始时调用)"""
        self._aligned_history.clear()


# ---------------------------------------------------------------------------
# Temporal Processor Module (Stream-DiffVSR inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class TemporalProcessorConfig:
    """时序感知解码器配置

    参考 Stream-DiffVSR 的轻量级时序感知解码器 (Temporal Processor Module)，
    接收当前帧与相邻帧特征，输出时序增强后的当前帧。
    """

    # 是否启用时序处理
    enabled: bool = True
    # 输入通道数
    in_channels: int = 64
    # 时序注意力头数
    num_heads: int = 4
    # 时序注意力 dropout
    attention_dropout: float = 0.0


class TemporalProcessorModule:
    """轻量级时序感知解码器

    参考 Stream-DiffVSR 的 Temporal Processor Module:
    轻量级时序感知解码器，接收当前帧 + 相邻帧特征，
    使用 1x1 conv + temporal attention 融合时序信息，
    输出时序增强后的当前帧。

    核心思路:
    1. 1x1 Conv: 将相邻帧特征投影到与当前帧相同的通道空间
    2. Temporal Attention: 在时间维度上计算注意力，融合相邻帧信息
    3. 残差连接: 保留当前帧的原始信息

    注意: 这是一个轻量级框架实现，实际的 temporal attention
    使用简化的点积注意力，而非完整的 transformer block。

    Usage:
        processor = TemporalProcessorModule(TemporalProcessorConfig())

        # 处理当前帧
        enhanced = processor.process(
            current_features=curr_feat,
            neighbor_features=[prev_feat, next_feat],
        )
    """

    def __init__(self, config: TemporalProcessorConfig | None = None):
        self.config = config or TemporalProcessorConfig()
        self._conv1x1: torch.nn.Conv2d | None = None

    def process(
        self,
        current_features: torch.Tensor,
        neighbor_features: list[torch.Tensor],
    ) -> torch.Tensor:
        """时序感知处理

        接收当前帧和相邻帧特征，通过 1x1 conv + temporal attention
        融合时序信息，输出增强后的当前帧特征。

        Args:
            current_features: 当前帧特征 (B, C, H, W) 或 (C, H, W)
            neighbor_features: 相邻帧特征列表 [(B, C, H, W), ...]

        Returns:
            时序增强后的当前帧特征
        """
        if not self.config.enabled or not neighbor_features:
            return current_features

        squeeze = False
        if current_features.ndim == 3:
            current_features = current_features.unsqueeze(0)
            squeeze = True

        b, c, h, w = current_features.shape

        # 1x1 Conv 投影: 将相邻帧投影到当前通道空间
        projected_neighbors = []
        for feat in neighbor_features:
            if feat.ndim == 3:
                feat = feat.unsqueeze(0)
            # 确保通道数一致
            if feat.shape[1] != c:
                feat = self._project_channels(feat, c)
            projected_neighbors.append(feat)

        # Temporal Attention: 在时间维度上融合
        # 拼接当前帧和所有相邻帧: (B, T, C, H, W)
        all_features = [current_features] + projected_neighbors
        stacked = torch.stack(all_features, dim=1)  # (B, T, C, H, W)

        # 简化的 temporal attention
        attended = self._temporal_attention(stacked)

        # 残差连接: 只取当前帧位置的结果
        result = current_features + attended[:, 0] - current_features
        # 使用 attended 当前帧 + 残差
        result = attended[:, 0]

        if squeeze:
            result = result.squeeze(0)

        return result

    def _project_channels(
        self,
        features: torch.Tensor,
        target_channels: int,
    ) -> torch.Tensor:
        """使用 1x1 conv 投影通道数

        Args:
            features: 输入特征 (B, C_in, H, W)
            target_channels: 目标通道数

        Returns:
            投影后的特征 (B, C_out, H, W)
        """
        # 使用简单的线性插值作为投影 (无需可学习参数的轻量实现)
        if features.shape[1] < target_channels:
            # 通道不足: 重复通道
            repeat_factor = target_channels // features.shape[1]
            remainder = target_channels % features.shape[1]
            projected = features.repeat(1, repeat_factor, 1, 1)
            if remainder > 0:
                projected = torch.cat(
                    [projected, features[:, :remainder]], dim=1
                )
        else:
            # 通道过多: 取前 target_channels 个通道
            projected = features[:, :target_channels]

        return projected

    def _temporal_attention(
        self,
        stacked_features: torch.Tensor,
    ) -> torch.Tensor:
        """简化的时序注意力

        在时间维度上计算简化的注意力权重并融合。

        Args:
            stacked_features: 堆叠的特征 (B, T, C, H, W)

        Returns:
            注意力融合后的特征 (B, T, C, H, W)
        """
        b, t, c, h, w = stacked_features.shape
        num_heads = self.config.num_heads

        # 将空间维度展平
        flat = stacked_features.reshape(b, t, c, h * w)  # (B, T, C, L)

        # 简化注意力: 计算当前帧与每个时序位置的相关性
        current = flat[:, 0:1]  # (B, 1, C, L)

        # 点积相似度: (B, 1, L) x (B, T, L) -> (B, T, L)
        # 简化为: 对每个时间步计算全局相似度
        similarity = torch.sum(
            current * flat, dim=2
        ) / (c ** 0.5)  # (B, T, L)

        # Softmax 归一化 (在时间维度上)
        attention = F.softmax(similarity, dim=1)  # (B, T, L)

        # 加权融合
        attention = attention.unsqueeze(2)  # (B, T, 1, L)
        weighted = flat * attention  # (B, T, C, L)
        result = weighted.reshape(b, t, c, h, w)

        return result


# ---------------------------------------------------------------------------
# 递归-并行混合架构 (RVRT inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class RecursiveParallelConfig:
    """递归-并行混合架构配置

    参考 RVRT 的递归-并行混合架构:
    clip 内的帧并行处理，clip 之间递归传递信息。
    """

    # 是否启用递归-并行混合
    enabled: bool = True
    # clip 大小: 每个 clip 包含的帧数
    clip_size: int = 4
    # clip 内是否并行处理
    parallel_within_clip: bool = True
    # clip 间递归传递的信息维度
    recurrent_dim: int = 64


class RecursiveParallelHybrid:
    """递归-并行混合架构

    参考 RVRT (Recurrent Video Restoration Transformer) 的架构:
    clip 内的帧可以并行处理 (利用 GPU 并行能力)，
    clip 之间采用递归方式传递信息 (保持长距离时序一致性)。

    核心思路:
    1. 将视频帧序列按 clip_size 划分为多个 clip
    2. clip 内: 各帧并行通过 transformer 处理，帧间通过自注意力交互
    3. clip 间: 递归传递隐藏状态，确保跨 clip 的时序一致性
    4. 每个 clip 的递归状态作为下一个 clip 的初始条件

    优势:
    - 并行性: clip 内帧并行处理，充分利用 GPU 算力
    - 一致性: clip 间递归传递，保持长距离时序依赖
    - 灵活性: clip_size 可调，平衡并行度和显存占用

    Usage:
        hybrid = RecursiveParallelHybrid(RecursiveParallelConfig())

        # 处理视频帧序列
        results = hybrid.process_frames(
            frames=video_frames,
            process_fn=model_forward,
        )
    """

    def __init__(self, config: RecursiveParallelConfig | None = None):
        self.config = config or RecursiveParallelConfig()
        self._recurrent_state: torch.Tensor | None = None

    def process_frames(
        self,
        frames: list[torch.Tensor],
        process_fn: Callable[[torch.Tensor, torch.Tensor | None], torch.Tensor],
    ) -> list[torch.Tensor]:
        """递归-并行混合处理视频帧序列

        将帧序列按 clip 划分，clip 内并行处理，clip 间递归传递。

        Args:
            frames: 视频帧列表，每帧为 (C, H, W) 张量
            process_fn: 帧处理函数，接收 (frame, recurrent_state) 返回处理结果

        Returns:
            处理后的帧列表
        """
        if not self.config.enabled:
            return [process_fn(f, None) for f in frames]

        clip_size = self.config.clip_size
        num_frames = len(frames)
        results: list[torch.Tensor] = []

        # 按 clip 划分帧序列
        for clip_start in range(0, num_frames, clip_size):
            clip_end = min(clip_start + clip_size, num_frames)
            clip_frames = frames[clip_start:clip_end]

            if self.config.parallel_within_clip and len(clip_frames) > 1:
                # clip 内并行处理
                clip_results = self._process_clip_parallel(
                    clip_frames, process_fn
                )
            else:
                # 串行处理 (clip 大小为 1 或禁用并行)
                clip_results = self._process_clip_sequential(
                    clip_frames, process_fn
                )

            results.extend(clip_results)

            # 更新递归状态: 使用 clip 最后一帧的结果
            if clip_results:
                self._recurrent_state = clip_results[-1].detach()

        return results

    def _process_clip_parallel(
        self,
        clip_frames: list[torch.Tensor],
        process_fn: Callable[[torch.Tensor, torch.Tensor | None], torch.Tensor],
    ) -> list[torch.Tensor]:
        """clip 内并行处理帧

        将 clip 内所有帧拼接为 batch，一次性通过处理函数，
        实现并行处理。

        Args:
            clip_frames: clip 内的帧列表
            process_fn: 帧处理函数

        Returns:
            处理后的帧列表
        """
        # 拼接为 batch: (B, C, H, W)
        batch = torch.stack(clip_frames, dim=0)

        # 统一使用当前递归状态
        recurrent = self._recurrent_state

        # 批量处理
        batch_result = process_fn(batch, recurrent)

        # 拆分回各帧
        if batch_result.ndim == clip_frames[0].ndim + 1:
            # 返回的是 batch 形式 (B, C, H, W)
            results = [batch_result[i] for i in range(batch_result.shape[0])]
        else:
            # 处理函数返回单个结果，回退到逐帧处理
            logger.warning("process_fn 未返回 batch 结果，回退到逐帧处理")
            results = self._process_clip_sequential(clip_frames, process_fn)

        return results

    def _process_clip_sequential(
        self,
        clip_frames: list[torch.Tensor],
        process_fn: Callable[[torch.Tensor, torch.Tensor | None], torch.Tensor],
    ) -> list[torch.Tensor]:
        """clip 内串行处理帧 (递归传递状态)

        Args:
            clip_frames: clip 内的帧列表
            process_fn: 帧处理函数

        Returns:
            处理后的帧列表
        """
        results = []
        local_state = self._recurrent_state

        for frame in clip_frames:
            result = process_fn(frame, local_state)
            results.append(result)
            # 更新局部递归状态
            local_state = result.detach()

        return results

    def reset(self) -> None:
        """重置递归状态 (新序列开始时调用)"""
        self._recurrent_state = None
