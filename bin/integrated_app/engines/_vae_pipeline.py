"""VAE encode/decode pipeline mixin for SeedVR2Engine.

Extracted from seedvr2_engine.py as part of structural refactoring
(phase 2A). Contains VAE tiled encode and decode methods.
"""

import contextlib
import logging

import torch
from einops import rearrange

from bin.integrated_app.engines._memory_utils import (
    DEFAULT_SCALING_FACTOR,
    _force_release_memory,
)

logger = logging.getLogger(__name__)


class _VAEPipelineMixin:
    """Mixin: pipeline methods extracted from SeedVR2Engine."""

    @torch.no_grad()
    def _vae_encode(self, samples: list[torch.Tensor]) -> list[torch.Tensor]:
        """VAE 编码: 像素空间 -> 潜空间，支持 tiled 编码

        与 ComfyUI/test_e2e.py 一致: 使用 vae.encode(x, tiled=True, tile_size=..., tile_overlap=...)
        集成 SCST 启发的自动 tile size 推荐和 NaN 检测回退。
        """
        from bin.integrated_app.optimization.inference.vae_tiled_enhance import (
            detect_nan,
            get_optimal_tile_size,
        )

        vae_cfg = self._model_config["vae"]
        use_sample = vae_cfg.get("use_sample", True)
        scale = vae_cfg.get("scaling_factor", DEFAULT_SCALING_FACTOR)
        shift = vae_cfg.get("shifting_factor", 0.0)
        dtype = getattr(torch, vae_cfg.get("dtype", "bfloat16"))

        # tiled VAE 配置 (默认值对齐 ComfyUI HD 工作流: encode_tiled=True, tile_overlap=128)
        tiled_cfg = getattr(self, "_vae_tiled_config", {})
        encode_tiled = tiled_cfg.get("encode_tiled", True)
        tile_size = tiled_cfg.get("encode_tile_size", 1024)
        tile_overlap = tiled_cfg.get("encode_tile_overlap", 128)
        auto_tile_size = tiled_cfg.get("auto_tile_size", True)

        # 自动 tile size 推荐 (SCST inspired)
        if auto_tile_size and encode_tiled:
            try:
                # 根据输入尺寸和 GPU 显存计算最优 tile size
                if samples and len(samples) > 0:
                    sample = samples[0]
                    if sample.ndim >= 3:
                        h, w = sample.shape[-2], sample.shape[-1]
                        recommended_ts, recommended_overlap = get_optimal_tile_size(
                            h, w, is_decoder=False, device=self.device
                        )
                        # 如果配置的 tile_size 太大，或 overlap 配置不合理（>=50% tile_size），使用推荐值
                        bad_overlap = tile_size > 0 and tile_overlap >= tile_size // 2
                        if tile_size <= 0 or tile_size > recommended_ts * 1.5 or bad_overlap:
                            logger.info(
                                f"VAE 编码自动 tile size: 原配置({tile_size}/{tile_overlap}) "
                                f"-> 推荐({recommended_ts}/{recommended_overlap})"
                                f"{' (overlap 过大)' if bad_overlap else ''}"
                            )
                            tile_size = recommended_ts
                            tile_overlap = recommended_overlap
            except Exception as e:
                logger.debug(f"自动 tile size 推荐失败: {e}")

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        latents = []
        oom_fallback_used = False
        for sample in samples:
            # sample: C T H W -> B C T H W
            batch = sample.unsqueeze(0).to(self.device, dtype)
            if hasattr(self.vae, "preprocess"):
                batch = self.vae.preprocess(batch)

            if encode_tiled:
                logger.info(f"VAE tiled 编码: tile_size={tile_size}, overlap={tile_overlap}")
                try:
                    enc_result = self.vae.encode(
                        batch,
                        tiled=True,
                        tile_size=(tile_size, tile_size),
                        tile_overlap=(tile_overlap, tile_overlap),
                    )
                except RuntimeError as e:
                    if "out of memory" in str(e).lower() and not oom_fallback_used:
                        logger.warning("VAE 编码 OOM，尝试更小的 tile size")
                        torch.cuda.empty_cache()
                        tile_size = max(tile_size // 2, 256)
                        tile_overlap = max(tile_overlap // 2, 32)
                        enc_result = self.vae.encode(
                            batch,
                            tiled=True,
                            tile_size=(tile_size, tile_size),
                            tile_overlap=(tile_overlap, tile_overlap),
                        )
                        oom_fallback_used = True
                    else:
                        raise
            else:
                enc_result = self.vae.encode(batch)

            # 提取 latent
            if use_sample:
                latent = enc_result.latent
            else:
                latent = enc_result.posterior.mode().squeeze(2)

            latent = latent.unsqueeze(2) if latent.ndim == 4 else latent

            # NaN 检测
            if encode_tiled and detect_nan(latent, "vae_encode_latent"):
                logger.warning("VAE 编码检测到 NaN，回退到非 tiled 编码")
                torch.cuda.empty_cache()
                enc_result = self.vae.encode(batch)
                if use_sample:
                    latent = enc_result.latent
                else:
                    latent = enc_result.posterior.mode().squeeze(2)
                latent = latent.unsqueeze(2) if latent.ndim == 4 else latent

            # channels-first -> channels-last + 缩放
            latent = rearrange(latent, "b c ... -> b ... c")
            latent = (latent - shift) * scale
            latents.append(latent.squeeze(0))  # 去掉 batch 维度

        return latents

    @torch.no_grad()
    @torch.no_grad()
    def _vae_decode(self, latents: list[torch.Tensor]) -> list[torch.Tensor]:
        """VAE 解码: 潜空间 -> 像素空间，支持 tiled 解码

        与 ComfyUI/test_e2e.py 一致: 使用 vae.decode(x, tiled=True, tile_size=..., tile_overlap=...)
        集成 SCST 启发的自动 tile size 推荐、OOM 回退和 NaN 检测。
        """
        from bin.integrated_app.optimization.inference.vae_tiled_enhance import (
            GroupNormAccumulator,
            TiledVAEHook,
            detect_nan,
            get_optimal_tile_size,
        )

        vae_cfg = self._model_config["vae"]
        scale = vae_cfg.get("scaling_factor", DEFAULT_SCALING_FACTOR)
        shift = vae_cfg.get("shifting_factor", 0.0)
        dtype = getattr(torch, vae_cfg.get("dtype", "bfloat16"))

        # tiled VAE 配置 (默认值对齐 ComfyUI 工作流: decode_tiled=True, decode_tile_size=1024)
        tiled_cfg = getattr(self, "_vae_tiled_config", {})
        decode_tiled = tiled_cfg.get("decode_tiled", True)
        tile_size = tiled_cfg.get("decode_tile_size", 1024)
        tile_overlap = tiled_cfg.get("decode_tile_overlap", 128)
        auto_tile_size = tiled_cfg.get("auto_tile_size", True)
        gaussian_blend = tiled_cfg.get("gaussian_blend", True)
        use_groupnorm_accum = tiled_cfg.get("groupnorm_accumulate", True)

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        # 准备 GroupNorm 累积器和 TiledVAEHook
        groupnorm_accum = None
        tiled_hook = None
        if decode_tiled and use_groupnorm_accum:
            try:
                groupnorm_accum = GroupNormAccumulator(self.vae)
                groupnorm_accum.start_accumulation()
            except Exception as e:
                logger.debug(f"GroupNormAccumulator init failed: {e}")
                groupnorm_accum = None

        if decode_tiled and gaussian_blend:
            try:
                tiled_hook = TiledVAEHook(self.vae)
                tiled_hook.install()
            except Exception as e:
                logger.debug(f"TiledVAEHook install failed: {e}")
                tiled_hook = None

        samples = []
        oom_fallback_used = False
        nan_fallback_used = False
        try:
            for latent in latents:
                # latent: ... C -> B ... C
                batch = latent.unsqueeze(0).to(self.device, dtype)
                batch = batch / scale + shift
                batch = rearrange(batch, "b ... c -> b c ...")
                batch = batch.squeeze(2)

                # 自动 tile size 推荐 (SCST inspired)
                # 重要: vae.decode 的 tile_size 参数为像素空间单位！VAE 内部自动 // 8 转换为潜空间
                current_tile_size = tile_size  # 像素空间
                current_tile_overlap = tile_overlap  # 像素空间
                if auto_tile_size and decode_tiled:
                    try:
                        if batch.ndim >= 4:
                            h_latent, w_latent = batch.shape[-2], batch.shape[-1]
                            # latent 空间尺寸 * 8 = 输出像素空间尺寸
                            h_pixel = h_latent * 8
                            w_pixel = w_latent * 8
                            # get_optimal_tile_size 直接返回像素空间推荐值
                            recommended_ts, recommended_overlap = get_optimal_tile_size(
                                h_pixel, w_pixel, is_decoder=True, device=self.device
                            )
                            # 如果配置的 tile_size 太大，或 overlap 配置不合理（>=50% tile_size），使用推荐值
                            bad_overlap = current_tile_size > 0 and current_tile_overlap >= current_tile_size // 2
                            if current_tile_size <= 0 or current_tile_size > recommended_ts * 1.5 or bad_overlap:
                                logger.info(
                                    f"VAE 解码自动 tile size (像素): 原配置({current_tile_size}/{current_tile_overlap})"
                                    f" -> 推荐({recommended_ts}/{recommended_overlap})"
                                    f"{' (overlap 过大)' if bad_overlap else ''}"
                                )
                                current_tile_size = recommended_ts
                                current_tile_overlap = recommended_overlap
                    except Exception as e:
                        logger.debug(f"自动 tile size 推荐失败: {e}")

                if decode_tiled:
                    logger.info(
                        f"VAE tiled 解码: tile_size={current_tile_size}, "
                        f"overlap={current_tile_overlap}, gaussian_blend={gaussian_blend}, "
                        f"groupnorm_accum={use_groupnorm_accum}"
                    )
                    try:
                        dec_result = self.vae.decode(
                            batch,
                            tiled=True,
                            tile_size=(current_tile_size, current_tile_size),
                            tile_overlap=(current_tile_overlap, current_tile_overlap),
                        )
                    except RuntimeError as e:
                        if "out of memory" in str(e).lower() and not oom_fallback_used:
                            logger.warning("VAE 解码 OOM，尝试更小的 tile size")
                            torch.cuda.empty_cache()
                            _force_release_memory()
                            # OOM 回退: 像素空间 tile size 减半，最小 256
                            current_tile_size = max(current_tile_size // 2, 256)
                            current_tile_overlap = max(current_tile_overlap // 2, 32)
                            dec_result = self.vae.decode(
                                batch,
                                tiled=True,
                                tile_size=(current_tile_size, current_tile_size),
                                tile_overlap=(current_tile_overlap, current_tile_overlap),
                            )
                            oom_fallback_used = True
                        elif "out of memory" in str(e).lower():
                            # 第二次 OOM，完全禁用 tiled
                            logger.warning("VAE 解码再次 OOM，回退到非 tiled 解码")
                            torch.cuda.empty_cache()
                            _force_release_memory()
                            dec_result = self.vae.decode(batch)
                        else:
                            raise

                    sample = dec_result.sample

                    # Gaussian 权重混合增强 (SCST/VEncancer inspired)
                    if gaussian_blend and getattr(self.vae, "_last_tile_outputs", None):
                        try:
                            from bin.integrated_app.optimization.inference.vae_tiled_enhance import blend_tiles_gaussian

                            tile_outputs = self.vae._last_tile_outputs
                            tile_positions = self.vae._last_tile_positions
                            if tile_outputs and tile_positions:
                                output_h, output_w = sample.shape[-2:]
                                # tile_size 已经是像素空间
                                actual_tile_size = getattr(self.vae, "_last_tile_size", current_tile_size)
                                actual_tile_overlap = getattr(self.vae, "_last_tile_overlap", current_tile_overlap)
                                sample = blend_tiles_gaussian(
                                    tile_outputs,
                                    tile_positions,
                                    (output_h, output_w),
                                    actual_tile_size,
                                    actual_tile_overlap,
                                    device=self.device,
                                    dtype=sample.dtype,
                                )
                                logger.info(f"VAE tiled: Gaussian 混合完成, {len(tile_outputs)} tiles")
                        except Exception as e:
                            logger.debug(f"Gaussian 混合失败: {e}")

                    # NaN 检测
                    if detect_nan(sample, "vae_decode_sample") and not nan_fallback_used:
                        logger.warning("VAE 解码检测到 NaN，回退到非 tiled 解码")
                        torch.cuda.empty_cache()
                        _force_release_memory()
                        dec_result = self.vae.decode(batch)
                        sample = dec_result.sample
                        nan_fallback_used = True
                else:
                    dec_result = self.vae.decode(batch)
                    sample = dec_result.sample

                if hasattr(self.vae, "postprocess"):
                    sample = self.vae.postprocess(sample)

                # 输出 NaN 最终检测
                if detect_nan(sample, "vae_decode_final"):
                    logger.error("VAE 解码最终输出仍包含 NaN，使用零填充")
                    sample = torch.nan_to_num(sample, nan=0.0, posinf=1.0, neginf=-1.0)

                samples.append(sample.squeeze(0))
        finally:
            # 清理 hook 和累积器
            if tiled_hook is not None:
                with contextlib.suppress(Exception):
                    tiled_hook.uninstall()
            if groupnorm_accum is not None:
                try:
                    groupnorm_accum.apply_accumulated_stats()
                except Exception as e:
                    logger.debug(f"GroupNorm stats apply failed: {e}")

        return samples

    # ------------------------------------------------------------------
    # 内部方法 - DiT 采样
    # ------------------------------------------------------------------
