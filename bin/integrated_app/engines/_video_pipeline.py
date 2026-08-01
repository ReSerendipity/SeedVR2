"""Video inference pipeline mixin for SeedVR2Engine.

Extracted from seedvr2_engine.py as part of structural refactoring
(phase 2A). Contains video inference implementation methods.
"""

import asyncio
import logging
import os
import random
import time

import numpy as np
import torch
from einops import rearrange
from torchvision.transforms import Compose, Lambda, Normalize

from bin.integrated_app.color_fix import apply_color_correction
from bin.integrated_app.engine_interface import RestoreResult
from bin.integrated_app.engines._memory_utils import (
    _HAS_TORCHVISION_IO,
    MAX_SEED,
    TEMPORAL_ALIGN_MULTIPLE,
    TILE_ALIGNMENT_FACTOR,
    _check_memory,
    _cleanup_cuda_cache,
    _DivisibleCrop,
    _log_memory,
    _NaResize,
    _RearrangeTCHW2CTHW,
    _tensor_to_uint8_np,
    read_video,
)
from bin.integrated_app.exceptions import InferenceCancelledError
from bin.integrated_app.optimization.gpu.cache_manager import get_cache_manager
from bin.integrated_app.optimization.gpu.memory_manager import clear_memory

logger = logging.getLogger(__name__)


class _VideoPipelineMixin:
    """Mixin: pipeline methods extracted from SeedVR2Engine."""

    async def infer_video(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """视频修复推理 - 在线程中运行以避免阻塞事件循环

        阶段1 (VAE编码): VAE在GPU, DiT在CPU
        阶段2 (DiT推理): DiT在GPU(BlockSwap动态交换), VAE在CPU
        阶段3 (VAE解码): VAE在GPU, DiT已清理
        阶段4 (后处理): 无模型
        """
        # REFACTOR [E4-1]: 每次推理开始前重置取消令牌
        self._reset_cancel_token()
        # VRAM 预检 (DiffBIR inspired)
        try:
            from bin.integrated_app.optimization.gpu.vram_monitor import VRAMPeakMonitor

            self._vram_monitor = VRAMPeakMonitor(device=self.device, enabled=True)
        except Exception:
            self._vram_monitor = None
        return await asyncio.to_thread(self._infer_video_impl, video_path, output_dir, **kwargs)

    def _infer_video_impl(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """视频修复推理同步实现 - 在线程中运行"""
        start_time = time.time()

        if not self._loaded:
            return RestoreResult(success=False, error="模型未加载")

        _check_memory()

        # 开始 VRAM 监控 (DiffBIR inspired)
        if self._vram_monitor is not None:
            self._vram_monitor.start_inference()

        tensor_cache = None
        try:
            tensor_cache = get_cache_manager()
            tensor_cache.clear()
        except Exception as e:
            logger.debug(f"TensorCacheManager init skipped: {e}")

        try:
            os.makedirs(output_dir, exist_ok=True)
            _check_memory()
            _log_memory("视频推理初始")

            # REFACTOR [E4-1]: 阶段0 检查取消信号
            self._check_cancelled("video:init")

            # 从配置读取推理参数
            inf = self._get_inference_config(**kwargs)

            # 分辨率处理: resolution 作为长边，max_resolution 作为上限
            res_h = kwargs.get("res_h", self.config.get("restore", {}).get("default_resolution_h", 1080))
            res_w = kwargs.get("res_w", self.config.get("restore", {}).get("default_resolution_w", 1920))
            if inf["max_resolution"] > 0:
                max_res = inf["max_resolution"]
                if max(res_h, res_w) > max_res:
                    scale = max_res / max(res_h, res_w)
                    res_h = int(res_h * scale)
                    res_w = int(res_w * scale)

            seed = inf["seed"]
            if seed == -1:
                seed = random.randint(0, MAX_SEED)
                logger.info(f"随机种子: {seed}")

            sp_size = kwargs.get("sp_size", self.config.get("restore", {}).get("sp_size", 1))
            cfg_scale = inf["cfg_scale"]
            cfg_rescale = inf["cfg_rescale"]
            sample_steps = inf["sample_steps"]
            color_fix_method = inf["color_correction"]
            input_noise_scale = inf["input_noise_scale"]
            latent_noise_scale = inf["latent_noise_scale"]

            logger.info(f"开始视频修复: {video_path} -> {res_w}x{res_h}, seed={seed}")

            # 获取视频信息
            video_info = self._ffmpeg.get_video_info(video_path)
            if not video_info:
                return RestoreResult(success=False, error="无法获取视频信息")

            total_frames = video_info.frame_count
            fps = video_info.fps
            out_fps = kwargs.get("out_fps", fps)
            logger.info(f"视频帧数: {total_frames}, 帧率: {fps}")

            # 长视频时间分段处理 (RVRT/DiffVSR inspired)
            temporal_segments = None
            segment_size = kwargs.get("segment_size", self.config.get("restore", {}).get("segment_size", 0))
            segment_overlap = kwargs.get("segment_overlap", self.config.get("restore", {}).get("segment_overlap", 0))
            if segment_size > 0 and total_frames > segment_size:
                try:
                    from bin.integrated_app.optimization.inference.tile_blend import compute_temporal_segments

                    temporal_segments = compute_temporal_segments(
                        total_frames=total_frames,
                        segment_size=segment_size,
                        overlap=segment_overlap,
                    )
                    logger.info(
                        f"长视频分段: {len(temporal_segments)} 段, 每段 {segment_size} 帧, 重叠 {segment_overlap} 帧"
                    )
                except Exception as e:
                    logger.debug(f"Temporal segments calculation skipped: {e}")

            # 读取视频
            # ROBUSTNESS [E4-2]: cv2.VideoCapture 必须在 finally 中 release，
            # 否则异常路径下文件句柄泄漏，导致后续 ffmpeg 操作失败
            cap = None
            try:
                if _HAS_TORCHVISION_IO:
                    video, _, info = read_video(video_path, output_format="TCHW")
                    video = video / 255.0
                    if out_fps is None:
                        out_fps = info.get("video_fps", fps)
                else:
                    # 使用 cv2 作为 fallback
                    import cv2

                    cap = cv2.VideoCapture(video_path)
                    frames = []
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frame = torch.from_numpy(frame).permute(2, 0, 1).float() / 255.0
                        frames.append(frame)
                    video = torch.stack(frames)  # T C H W
            finally:
                # ROBUSTNESS [E4-2]: 确保视频句柄释放
                if cap is not None:
                    cap.release()

            # 构建变换
            video_transform = self._build_video_transform(res_h, res_w)

            # 编码
            cond_latent = video_transform(video.to(self.device))
            ori_length = cond_latent.shape[1]
            input_video = cond_latent.clone()

            # 视频帧数对齐
            cond_latent = self._cut_videos(cond_latent, sp_size)

            # ==================== 阶段1: VAE 编码 ====================
            # VAE 在 GPU, DiT 在 CPU 或未加载
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage1-vae-encode")
            logger.info("阶段1: VAE 编码 (VAE=GPU)")
            # VRAM 监控: VAE 编码阶段
            vram_stage = self._vram_monitor.stage("vae_encode") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                # 注意: BlockSwap 的 _protect_model_from_move 阻止了 dit.to("cpu")
                self.vae.to(device=self.device)
                logger.info(f"VAE 编码: {cond_latent.size()}")
                cond_latents = self._vae_encode([cond_latent])
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 释放 VAE，为 DiT 腾出显存
            self.vae.to(device="cpu")
            self.vae.zero_grad(set_to_none=True)
            clear_memory(deep=False, force=True)

            # ==================== 阶段2: DiT 采样 ====================
            # DiT 在 GPU (BlockSwap 动态交换), VAE 在 CPU
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage2-dit-sample")
            logger.info("阶段2: DiT 采样 (DiT=GPU/BlockSwap, VAE=CPU)")
            # VRAM 监控: DiT 采样阶段
            vram_stage = self._vram_monitor.stage("dit_sample") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                if self.dit is None:
                    # DiT 已在之前的推理中被销毁或延迟加载，需要加载
                    logger.info("DiT 模型按需加载...")
                    # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_dit_model，
                    # 不再修改 self.config 全局状态
                    model_cfg = self.config.get("model", {})
                    self.dit = self._load_dit_model(
                        model_size=self._dit_model_size,
                        model_config=self._model_config,
                        checkpoint_path=self._dit_checkpoint_path,
                        precision=self._dit_precision,
                        device=self.device,
                        blocks_to_swap=inf.get("blocks_to_swap", model_cfg.get("blocks_to_swap", 0)),
                        swap_io_components=inf.get("swap_io_components", model_cfg.get("swap_io_components", False)),
                        offload_device=inf.get("offload_device", model_cfg.get("offload_device", "cpu")),
                        attention_mode=inf.get("attention_mode", model_cfg.get("attention_mode", "sdpa")),
                    )

                # 文本嵌入
                text_embeds = self._get_text_embeds()

                # DiT 采样
                logger.info("DiT 采样...")
                # Tensor Cache: 缓存 cond_latents 以释放 VRAM
                if tensor_cache is not None:
                    tensor_cache.maybe_cache_tensor(cond_latents, "dit_cond_latents")
                    cond_latents = None  # 释放引用

                samples = self._generation_step(
                    cond_latents=cond_latents,
                    text_embeds=text_embeds,
                    cfg_scale=cfg_scale,
                    cfg_rescale=cfg_rescale,
                    sample_steps=sample_steps,
                    seed=seed,
                    input_noise_scale=input_noise_scale,
                    latent_noise_scale=latent_noise_scale,
                    restoration_guidance_scale=inf.get("restoration_guidance_scale", 0.0),
                )

                # Tensor Cache: 恢复 cond_latents（如果被缓存）
                if tensor_cache is not None and cond_latents is None:
                    restored = tensor_cache.restore_tensor("dit_cond_latents", self.device)
                    if restored is not None:
                        cond_latents = restored
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 完全销毁 DiT 释放全部 VRAM（BlockSwap 阻止了 model.to("cpu") 的正常执行）
            self._destroy_dit()

            # ==================== 阶段3: VAE 解码 ====================
            # VAE 在 GPU, DiT 已销毁
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage3-vae-decode")
            logger.info("阶段3: VAE 解码 (VAE=GPU, DiT已销毁)")
            # VRAM 监控: VAE 解码阶段
            vram_stage = self._vram_monitor.stage("vae_decode") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                self.vae.to(device=self.device)
                decoded = self._vae_decode(samples)
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 释放 VAE
            self.vae.to(device="cpu")
            clear_memory(deep=False, force=True)

            # ==================== 阶段4: 后处理 ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage4-postprocess")
            logger.info("阶段4: 后处理")
            # VRAM 监控: 后处理阶段
            vram_stage = self._vram_monitor.stage("postprocess") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                sample = decoded[0]
                # C T H W -> T C H W
                if sample.ndim == 3:
                    sample = rearrange(sample[:, None], "c t h w -> t c h w")
                else:
                    sample = rearrange(sample, "c t h w -> t c h w")

                # 截断到原始长度
                if ori_length < sample.shape[0]:
                    sample = sample[:ori_length]

                # 颜色校正和后处理
                from bin.integrated_app.optimization.inference.post_processing import (
                    apply_sharpening,
                    wavelet_reconstruction,
                )

                postprocess_cfg = self.config.get("postprocessing", {})
                enable_wavelet = postprocess_cfg.get("wavelet_reconstruction", False)  # 视频默认关闭小波重建以节省时间
                sharpen_strength = postprocess_cfg.get("video_sharpen_strength", 0.0)

                input_frames = (
                    rearrange(input_video, "c t h w -> t c h w")
                    if input_video.ndim == 4
                    else rearrange(input_video[:, None], "c t h w -> t c h w")
                )
                input_frames_cpu = input_frames[: sample.shape[0]].cpu()

                sample_np = _tensor_to_uint8_np(sample)
                input_np = _tensor_to_uint8_np(input_frames_cpu)

                restored_frames = []
                # Feature propagation: temporal consistency enhancement (Upscale-A-Video inspired)
                # 在相邻帧间传播特征，提升时间一致性
                temporal_propagator = None
                temporal_propagation_enabled = self.config.get("inference", {}).get("temporal_propagation", True)
                if temporal_propagation_enabled:
                    try:
                        from bin.integrated_app.optimization.inference.temporal_processing import FeaturePropagation

                        prop_weight = postprocess_cfg.get("temporal_propagation_weight", 0.2)
                        temporal_propagator = FeaturePropagation(propagation_weight=prop_weight)
                    except Exception as e:
                        logger.debug(f"FeaturePropagation init skipped: {e}")

                prev_frame = None
                for i in range(sample_np.shape[0]):
                    frame = sample_np[i].transpose(1, 2, 0)  # C H W -> H W C
                    ref = input_np[i].transpose(1, 2, 0)
                    if color_fix_method != "none":
                        frame = apply_color_correction(frame, ref, method=color_fix_method)

                    # 小波重建后处理 (视频可选，默认关闭以节省时间)
                    if enable_wavelet:
                        try:
                            level = postprocess_cfg.get("wavelet_level", 2)
                            low_freq_weight = postprocess_cfg.get("low_freq_weight", 0.8)
                            frame = wavelet_reconstruction(frame, ref, level=level, low_freq_weight=low_freq_weight)
                        except Exception as e:
                            logger.debug(f"Video wavelet_reconstruction skipped: {e}")

                    # 视频锐化
                    if sharpen_strength > 0:
                        try:
                            frame = apply_sharpening(frame, strength=sharpen_strength, method="unsharp_mask")
                        except Exception as e:
                            logger.debug(f"Video sharpening skipped: {e}")

                    # Apply temporal feature propagation
                    if temporal_propagator is not None:
                        frame = temporal_propagator.propagate(
                            current_frame=frame,
                            previous_frame=prev_frame,
                        )
                    prev_frame = frame
                    restored_frames.append(frame)

                # 保存
                import mediapy

                output_filename = os.path.basename(video_path)
                output_name = os.path.splitext(output_filename)[0] + "_restored.mp4"
                output_path = os.path.join(output_dir, output_name)

                # 长视频分段混合 (RVRT/DiffVSR inspired)
                if temporal_segments is not None and len(temporal_segments) > 1:
                    try:
                        from bin.integrated_app.optimization.inference.tile_blend import blend_temporal_segments

                        # 将 restored_frames 转换为 tensor
                        frames_tensor = torch.from_numpy(np.array(restored_frames))  # T H W C
                        frames_tensor = frames_tensor.permute(0, 3, 1, 2)  # T C H W
                        blended = blend_temporal_segments(
                            segment_results=[frames_tensor],
                            segments=temporal_segments,
                            total_frames=total_frames,
                            overlap=segment_overlap,
                        )
                        # 混合后转换回 numpy
                        restored_frames = blended.permute(0, 2, 3, 1).numpy()  # T H W C
                        logger.info(f"长视频分段混合完成: {len(restored_frames)} 帧")
                    except Exception as e:
                        logger.debug(f"Temporal segments blending skipped: {e}")

                if len(restored_frames) == 1:
                    mediapy.write_image(output_path, restored_frames[0])
                else:
                    mediapy.write_video(output_path, np.array(restored_frames), fps=out_fps)

                # Tensor Cache: 清理缓存
                if tensor_cache is not None:
                    tensor_cache.clear()
                    cache_stats = tensor_cache.get_stats()
                    logger.info(
                        f"Tensor Cache 统计: cached={cache_stats['total_cached']}, "
                        f"restored={cache_stats['total_restored']}, "
                        f"peak={cache_stats['peak_cache_mb']:.1f}MB"
                    )

                # VRAM 监控: 结束并输出报告
                if self._vram_monitor is not None:
                    self._vram_monitor.end_inference()
                    self._vram_monitor.log_report()
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            _cleanup_cuda_cache(deep=True)

            processing_time = time.time() - start_time
            return RestoreResult(
                success=True,
                output_path=output_path,
                processing_time=processing_time,
                metadata={
                    "model_size": self.model_size,
                    "precision": self.precision,
                    "input_frames": total_frames,
                    "output_resolution": f"{res_w}x{res_h}",
                    "fps": out_fps,
                    "blockswap_active": self._blockswap_active,
                    "processing_fps": total_frames / processing_time if processing_time > 0 else 0,
                    "avg_frame_time_ms": (processing_time / total_frames * 1000) if total_frames > 0 else 0,
                    "cfg_scale": cfg_scale,
                    "sample_steps": sample_steps,
                    "inference_mode": inf["inference_mode"],
                },
            )

        except InferenceCancelledError as e:
            logger.warning(f"视频推理被取消: {e}")
            self._cleanup_after_error()
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )
        except Exception as e:
            logger.error(f"视频修复失败: {e}", exc_info=True)
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)

    def _build_video_transform(self, res_h: int, res_w: int) -> Compose:
        """构建视频/图像预处理变换流水线

        创建与官方 ComfyUI 工作流一致的预处理变换序列，按顺序执行:
        1. _NaResize: 按短边缩放到目标分辨率（area 插值，保持长宽比）
        2. Clamp: 将像素值裁剪到 [0, 1] 范围
        3. _DivisibleCrop: 裁剪到 tile_size 整数倍，避免 VAE 分块边界问题
        4. Normalize: 标准化到 [-1, 1]（均值 0.5，标准差 0.5）
        5. _RearrangeTCHW2CTHW: 将 T C H W 重排为 C T H W（适配模型输入格式）

        Args:
            res_h: 目标高度
            res_w: 目标宽度

        Returns:
            Compose: torchvision Compose 变换对象
        """
        return Compose(
            [
                _NaResize(
                    resolution=(res_h * res_w) ** 0.5,
                    mode="area",
                    downsample_only=False,
                ),
                Lambda(lambda x: torch.clamp(x, 0.0, 1.0)),
                _DivisibleCrop((TILE_ALIGNMENT_FACTOR, TILE_ALIGNMENT_FACTOR)),
                Normalize(0.5, 0.5),
                _RearrangeTCHW2CTHW(),
            ]
        )

    @staticmethod
    def _cut_videos(videos: torch.Tensor, sp_size: int) -> torch.Tensor:
        """视频帧数对齐填充

        将视频帧数填充到 TEMPORAL_ALIGN_MULTIPLE * sp_size 的整数倍，
        确保 VAE 时间下采样时不会出错。使用最后一帧作为填充内容。

        Args:
            videos: 视频张量，形状 B C T H W
            sp_size: 空间分块大小（影响时间对齐粒度）

        Returns:
            torch.Tensor: 填充后的视频张量，帧数已对齐
        """
        t = videos.size(1)
        align_frames = TEMPORAL_ALIGN_MULTIPLE * sp_size
        if t == 1:
            return videos
        if t <= align_frames:
            padding = [videos[:, -1].unsqueeze(1)] * (align_frames - t + 1)
            padding = torch.cat(padding, dim=1)
            videos = torch.cat([videos, padding], dim=1)
            return videos
        if (t - 1) % align_frames == 0:
            return videos
        else:
            padding = [videos[:, -1].unsqueeze(1)] * (align_frames - ((t - 1) % align_frames))
            padding = torch.cat(padding, dim=1)
            videos = torch.cat([videos, padding], dim=1)
            assert (videos.size(1) - 1) % align_frames == 0
            return videos
