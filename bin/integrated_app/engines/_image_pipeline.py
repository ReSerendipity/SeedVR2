"""Image inference pipeline mixin for SeedVR2Engine.

Extracted from seedvr2_engine.py as part of structural refactoring
(phase 2A). Contains image inference and post-processing methods.
"""

import asyncio
import gc
import logging
import os
import random
import time
from pathlib import Path

import numpy as np
import torch
from einops import rearrange
from PIL import Image as PILImage

from bin.integrated_app.color_fix import apply_color_correction
from bin.integrated_app.engine_interface import RestoreResult
from bin.integrated_app.engines._memory_utils import (
    MAX_SEED,
    ImageInferenceConfig,
    _check_memory,
    _cleanup_cuda_cache,
    _log_memory,
    _tensor_to_uint8_np,
)
from bin.integrated_app.exceptions import InferenceCancelledError

logger = logging.getLogger(__name__)


class _ImagePipelineMixin:
    """Mixin: pipeline methods extracted from SeedVR2Engine."""

    async def infer_image(
        self,
        image_path: str,
        output_dir: str,
        config: ImageInferenceConfig | None = None,
        **kwargs,
    ) -> RestoreResult:
        """图像修复推理 - 在线程中运行以避免阻塞事件循环

        阶段1: 加载VAE → 编码 → 销毁VAE
        阶段2: 加载DiT → 采样 → 销毁DiT
        阶段3: 加载VAE → 解码 → 销毁VAE
        阶段4: 后处理 (无模型)

        任何时刻 RAM 中最多只有一个大模型，内存超过 90% 立即终止

        Args:
            image_path: 输入图像路径
            output_dir: 输出目录
            config: 图像推理配置 (为 None 时从 self.config 构建默认配置)
            **kwargs: 额外参数，会覆盖 config 中的同名字段 (兼容旧调用方)
        """
        if config is None:
            config = ImageInferenceConfig.from_config_dict(self.config, **kwargs)
        elif kwargs:
            # kwargs 覆盖 config 字段
            for k, v in kwargs.items():
                if hasattr(config, k):
                    object.__setattr__(config, k, v)

        # REFACTOR [E4-1]: 每次推理开始前重置取消令牌
        self._reset_cancel_token()
        return await asyncio.to_thread(self._infer_image_impl, image_path, output_dir, config)

    def _prepare_image_input(self, image_path: str, resolution: int) -> tuple:
        """读取图像并预处理为模型输入

        Args:
            image_path: 输入图像路径
            resolution: 目标分辨率 (长边)

        Returns:
            (cond_latent, input_video, res_h, res_w, scale_factor)
        """

        orig_img = PILImage.open(image_path).convert("RGB")
        orig_w, orig_h = orig_img.size

        # 分辨率计算
        scale_factor = 2.0
        if resolution > 0:
            target_long = resolution
            current_long = max(orig_h, orig_w)
            if target_long > current_long:
                scale_factor = target_long / current_long
            else:
                scale_factor = 1.0

        res_h = int(orig_h * scale_factor)
        res_w = int(orig_w * scale_factor)
        res_h = res_h - (res_h % 2)
        res_w = res_w - (res_w % 2)

        # 预处理图像 (与 ComfyUI 工作流一致: [0,1] 传入 transform)
        img_np = np.array(orig_img).astype(np.float32) / 255.0  # [0, 1]
        image = torch.from_numpy(img_np).permute(2, 0, 1)  # C H W
        image = image.unsqueeze(0)  # T C H W (T=1)
        del orig_img, img_np
        gc.collect()

        # 变换: NaResize + DivisibleCrop
        video_transform = self._build_video_transform(res_h, res_w)
        cond_latent = video_transform(image)  # C T H W
        input_video = cond_latent.clone()
        del image
        gc.collect()

        return cond_latent, input_video, res_h, res_w, scale_factor

    def _postprocess_output(
        self,
        decoded: list,
        input_video: torch.Tensor,
        color_fix_method: str,
        res_h: int,
        res_w: int,
        image_path: str,
        output_dir: str,
        scale_factor: float,
        inf: dict,
        cfg_scale: float,
        sample_steps: int,
        blockswap_was_active: bool,
    ) -> RestoreResult:
        """后处理: 颜色校正、保存输出、创建 RestoreResult

        集成多种后处理增强:
        - 颜色校正 (LAB/Wavelet/AdaIN)
        - 小波重建锐化增强 (DiffBIR inspired)
        - Alpha 通道处理 (waifu2x inspired)
        - EXIF 元数据复制 (upscayl inspired)
        - 图像锐化增强 (Real-ESRGAN inspired)
        - 文本修复流水线 (Vivid-VR inspired, 可选)

        Args:
            decoded: VAE 解码结果
            input_video: 原始输入视频张量 (用于颜色校正参考)
            color_fix_method: 颜色校正方法
            res_h, res_w: 输出分辨率
            image_path: 输入图像路径
            output_dir: 输出目录
            scale_factor: 缩放因子
            inf: 推理配置字典 (含 inference_mode 等)
            cfg_scale: CFG 缩放
            sample_steps: 采样步数
            blockswap_was_active: BlockSwap 是否激活

        Returns:
            RestoreResult
        """

        from bin.integrated_app.optimization.post_processing import (
            TextRestorationConfig,
            TextRestorationPipeline,
            apply_sharpening,
            copy_exif_metadata,
            extract_alpha_from_image,
            merge_alpha_to_image,
            wavelet_reconstruction,
        )

        # 读取原始图像，处理 Alpha 通道
        original_alpha = None
        try:
            orig_img_pil = PILImage.open(image_path)
            orig_img_np = np.array(orig_img_pil)
            _, original_alpha = extract_alpha_from_image(orig_img_np)
            del orig_img_pil, orig_img_np
        except Exception as e:
            logger.debug(f"Alpha 通道提取失败: {e}")

        sample = decoded[0]  # [C, T, H, W] or [C, H, W]

        # 处理时间维度: C T H W -> C H W (单帧图像)
        if sample.ndim == 4:
            sample = rearrange(sample, "c t h w -> t c h w")  # T C H W
            sample = sample[0]  # C H W

        result_np = _tensor_to_uint8_np(sample)
        result_np = result_np.transpose(1, 2, 0)  # C H W -> H W C

        del sample, decoded
        gc.collect()

        ref_np = None
        if input_video is not None:
            ref = input_video
            if ref.ndim == 4:
                ref = rearrange(ref, "c t h w -> t c h w")[0]
            ref_np = _tensor_to_uint8_np(ref)
            ref_np = ref_np.transpose(1, 2, 0)

        # 颜色校正
        if color_fix_method != "none" and ref_np is not None:
            result_np = apply_color_correction(result_np, ref_np, method=color_fix_method)

        # 小波重建后处理 (DiffBIR inspired) - 提升锐度
        postprocess_cfg = self.config.get("postprocessing", {})
        enable_wavelet = postprocess_cfg.get("wavelet_reconstruction", True)
        if enable_wavelet and ref_np is not None:
            try:
                level = postprocess_cfg.get("wavelet_level", 3)
                low_freq_weight = postprocess_cfg.get("low_freq_weight", 0.8)
                result_np = wavelet_reconstruction(result_np, ref_np, level=level, low_freq_weight=low_freq_weight)
                logger.debug(f"小波重建应用: level={level}, low_freq_weight={low_freq_weight}")
            except Exception as e:
                logger.debug(f"wavelet_reconstruction skipped: {e}")

        # 锐化增强 (Real-ESRGAN inspired)
        sharpen_strength = postprocess_cfg.get("sharpen_strength", 0.0)
        if sharpen_strength > 0:
            try:
                result_np = apply_sharpening(result_np, strength=sharpen_strength, method="unsharp_mask")
                logger.debug(f"锐化增强应用: strength={sharpen_strength}")
            except Exception as e:
                logger.debug(f"sharpening skipped: {e}")

        # 文本修复流水线 (Vivid-VR inspired, 可选)
        enable_text_restoration = postprocess_cfg.get("text_restoration", False)
        if enable_text_restoration and ref_np is not None:
            try:
                text_config = TextRestorationConfig(
                    enabled=True,
                    ocr_languages=postprocess_cfg.get("ocr_languages", ["ch_sim", "en"]),
                    ocr_confidence_threshold=postprocess_cfg.get("ocr_confidence", 0.5),
                    text_enhance_method=postprocess_cfg.get("text_enhance_method", "sharpen"),
                )
                text_pipeline = TextRestorationPipeline(text_config)
                result_np = text_pipeline.process(result_np, ref_np)
                logger.info("文本修复流水线已应用")
            except Exception as e:
                logger.debug(f"text_restoration skipped: {e}")

        # 合并 Alpha 通道 (如果有)
        if original_alpha is not None:
            try:
                result_np = merge_alpha_to_image(result_np, original_alpha)
                logger.debug("Alpha 通道已合并")
            except Exception as e:
                logger.debug(f"Alpha 通道合并失败: {e}")

        del input_video, ref_np, original_alpha
        gc.collect()

        # 保存
        output_name = f"SeedVR2_{Path(image_path).stem}_000001.png"
        output_path = os.path.join(output_dir, output_name)
        PILImage.fromarray(result_np).save(output_path)

        # 复制 EXIF 元数据 (upscayl inspired)
        enable_exif_copy = postprocess_cfg.get("copy_exif", True)
        if enable_exif_copy:
            try:
                copy_exif_metadata(image_path, output_path)
            except Exception as e:
                logger.debug(f"EXIF 复制失败: {e}")

        # 计算输出统计
        if result_np.shape[-1] >= 3:
            mean_val = result_np[..., :3].mean()
            std_val = result_np[..., :3].std()
        else:
            mean_val = result_np.mean()
            std_val = result_np.std()
        logger.info(f"输出: {result_np.shape[1]}x{result_np.shape[0]}, Mean={mean_val:.1f}, Std={std_val:.1f}")
        logger.info(f"保存: {output_path}")

        del result_np
        _cleanup_cuda_cache(deep=True)

        return RestoreResult(
            success=True,
            output_path=output_path,
            processing_time=0.0,  # 由调用方填充
            metadata={
                "model_size": self.model_size,
                "precision": self.precision,
                "output_resolution": f"{res_w}x{res_h}",
                "scale_factor": scale_factor,
                "inference_mode": inf["inference_mode"],
                "cfg_scale": cfg_scale,
                "sample_steps": sample_steps,
                "blockswap_active": blockswap_was_active,
                "mean": float(mean_val),
                "std": float(std_val),
                "postprocessing": {
                    "wavelet": enable_wavelet,
                    "sharpen": sharpen_strength > 0,
                    "text_restoration": enable_text_restoration,
                },
            },
        )

    def _infer_image_impl(
        self,
        image_path: str,
        output_dir: str,
        cfg: ImageInferenceConfig,
    ) -> RestoreResult:
        """图像修复推理同步实现 - 在线程中运行

        REFACTOR [B1-1] [P3-1]: 删除 copy.deepcopy(self.config) 配置快照
        - 原实现通过修改 self.config 全局状态传递请求级参数给 _load_dit_model/_load_vae_model，
          违反单一职责原则（引擎级配置不应被单个请求污染），且 deepcopy 大字典有性能开销
        - 改为显式参数化 _load_dit_model / _load_vae_model，参数直接从 cfg 读取
        - 删除 finally 中的 self.config = _config_snapshot 恢复逻辑
        """
        start_time = time.time()

        if not self._loaded:
            return RestoreResult(success=False, error="模型未加载")

        try:
            os.makedirs(output_dir, exist_ok=True)
            _check_memory()
            _log_memory("推理初始")

            # REFACTOR [E4-1]: 阶段0 检查取消信号
            self._check_cancelled("image:init")

            # 从 ImageInferenceConfig 读取推理参数
            inf = self._get_inference_config(
                seed=cfg.seed,
                resolution=cfg.resolution,
                max_resolution=cfg.max_resolution,
                batch_size=cfg.batch_size,
                uniform_batch_size=cfg.uniform_batch_size,
                color_correction=cfg.color_correction,
                temporal_overlap=cfg.temporal_overlap,
                prepend_frames=cfg.prepend_frames,
                input_noise_scale=cfg.input_noise_scale,
                latent_noise_scale=cfg.latent_noise_scale,
                attention_mode=cfg.attention_mode,
                enable_debug=cfg.enable_debug,
            )

            seed = inf["seed"]
            if seed == -1:
                seed = random.randint(0, MAX_SEED)

            cfg_scale = inf["cfg_scale"]
            cfg_rescale = inf["cfg_rescale"]
            sample_steps = inf["sample_steps"]
            color_fix_method = inf["color_correction"]
            input_noise_scale = inf["input_noise_scale"]
            latent_noise_scale = inf["latent_noise_scale"]

            # 读取并预处理图像
            cond_latent, input_video, res_h, res_w, scale_factor = self._prepare_image_input(
                image_path, inf["resolution"]
            )
            logger.info(
                f"图像修复: {image_path}, -> {res_w}x{res_h}, "
                f"seed={seed}, mode={inf['inference_mode']}, cfg={cfg_scale}, steps={sample_steps}"
            )

            # REFACTOR [B1-1] [P3-1]: 构建请求级 VAE tiled 配置（从 cfg 读取）
            # 替代原 self.config["model"]["vae"][...] = ... 的配置污染
            vae_tiled_config = {
                "encode_tiled": cfg.encode_tiled,
                "encode_tile_size": cfg.encode_tile_size,
                "encode_tile_overlap": cfg.encode_tile_overlap,
                "decode_tiled": cfg.decode_tiled,
                "decode_tile_size": cfg.decode_tile_size,
                "decode_tile_overlap": cfg.decode_tile_overlap,
                "tile_debug": cfg.tile_debug,
                "offload_device": cfg.vae_offload_device,
                "cache_model": cfg.vae_cache_model,
            }

            logger.info(
                f"工作流参数: dit_model={cfg.dit_model}, dit_device={cfg.dit_device}, "
                f"blocks_to_swap={cfg.blocks_to_swap}, swap_io_components={cfg.swap_io_components}, "
                f"attention_mode={cfg.attention_mode}, "
                f"vae_model={cfg.vae_model}, vae_device={cfg.vae_device}, "
                f"encode_tiled={cfg.encode_tiled}, decode_tiled={cfg.decode_tiled}, "
                f"encode_tile_size={cfg.encode_tile_size}, decode_tile_size={cfg.decode_tile_size}, "
                f"tile_debug={cfg.tile_debug}, "
                f"resolution={cfg.resolution}, seed={cfg.seed}, color_correction={cfg.color_correction}"
            )

            # ==================== 阶段1: 加载VAE → 编码 → 销毁VAE ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage1-vae-encode")
            logger.info("=" * 60)
            logger.info("阶段1: VAE 编码")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段1开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_vae_model，
            # 不再修改 self.config 全局状态
            self.vae = self._load_vae_model(
                model_config=self._model_config,
                checkpoint_path=self._vae_checkpoint_path,
                device=self.device,
                vae_tiled_config=vae_tiled_config,
            )
            self.vae.to(device=self.device)
            _log_memory("VAE加载到GPU后")
            _check_memory()

            cond_latents = self._vae_encode([cond_latent])
            del cond_latent
            gc.collect()

            # 销毁 VAE 释放内存，为 DiT 腾出空间
            self._destroy_vae()
            _log_memory("VAE销毁后")
            _check_memory()

            # ==================== 阶段2: 加载DiT → 采样 → 销毁DiT ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage2-dit-sample")
            logger.info("=" * 60)
            logger.info("阶段2: DiT 采样")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段2开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_dit_model，
            # 不再修改 self.config 全局状态
            self.dit = self._load_dit_model(
                model_size=self._dit_model_size,
                model_config=self._model_config,
                checkpoint_path=self._dit_checkpoint_path,
                precision=self._dit_precision,
                device=self.device,
                blocks_to_swap=cfg.blocks_to_swap,
                swap_io_components=cfg.swap_io_components,
                offload_device=cfg.dit_offload_device,
                attention_mode=cfg.attention_mode,
            )
            _log_memory("DiT加载后")
            _check_memory()

            text_embeds = self._get_text_embeds()

            logger.info(f"开始 DiT 采样: cfg={cfg_scale}, steps={sample_steps}, blockswap={self._blockswap_active}")
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

            # 释放中间变量
            del cond_latents, text_embeds
            gc.collect()

            # 保存 blockswap 状态 (销毁 DiT 后会清除标志)
            blockswap_was_active = self._blockswap_active

            # 销毁 DiT 释放全部 VRAM
            self._destroy_dit()
            _log_memory("DiT销毁后")
            _check_memory()

            # ==================== 阶段3: 加载VAE → 解码 → 销毁VAE ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage3-vae-decode")
            logger.info("=" * 60)
            logger.info("阶段3: VAE 解码")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段3开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_vae_model（复用 vae_tiled_config）
            self.vae = self._load_vae_model(
                model_config=self._model_config,
                checkpoint_path=self._vae_checkpoint_path,
                device=self.device,
                vae_tiled_config=vae_tiled_config,
            )
            self.vae.to(device=self.device)
            _log_memory("VAE重新加载到GPU后")
            _check_memory()

            decoded = self._vae_decode(samples)

            # 释放 samples
            del samples
            gc.collect()

            # 销毁 VAE
            self._destroy_vae()
            _log_memory("VAE最终销毁后")

            # ==================== 阶段4: 后处理 ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage4-postprocess")
            logger.info("=" * 60)
            logger.info("阶段4: 后处理")
            logger.info("=" * 60)
            result = self._postprocess_output(
                decoded=decoded,
                input_video=input_video,
                color_fix_method=color_fix_method,
                res_h=res_h,
                res_w=res_w,
                image_path=image_path,
                output_dir=output_dir,
                scale_factor=scale_factor,
                inf=inf,
                cfg_scale=cfg_scale,
                sample_steps=sample_steps,
                blockswap_was_active=blockswap_was_active,
            )
            result.processing_time = time.time() - start_time
            return result

        except InferenceCancelledError as e:
            logger.warning(f"图像推理被取消: {e}")
            self._cleanup_after_error()
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )

        except MemoryError as e:
            logger.error(f"内存不足，紧急终止推理: {e}")
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)

        except Exception as e:
            logger.error(f"图像修复失败: {e}", exc_info=True)
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)
        # REFACTOR [B1-1]: 删除 finally 中的 self.config = _config_snapshot
        # 显式参数化后不再修改 self.config，无需恢复

    async def infer_batch(self, input_dir: str, output_dir: str, **kwargs) -> list[RestoreResult]:
        """批量图像修复 - 从文件夹加载图片并逐张处理

        Args:
            input_dir: 输入图片文件夹路径
            output_dir: 输出目录
            **kwargs: 传递给 infer_image 的参数

        Returns:
            每张图片的修复结果列表
        """
        if not self._loaded:
            return [RestoreResult(success=False, error="模型未加载")]

        input_path = Path(input_dir)
        if not input_path.is_dir():
            return [RestoreResult(success=False, error=f"输入目录不存在: {input_dir}")]

        # 支持的图片格式
        image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}
        image_files = sorted([f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in image_extensions])

        if not image_files:
            return [RestoreResult(success=False, error=f"目录中未找到图片: {input_dir}")]

        logger.info(f"批量处理: 找到 {len(image_files)} 张图片")
        os.makedirs(output_dir, exist_ok=True)

        results = []
        for i, image_file in enumerate(image_files):
            logger.info(f"处理 [{i+1}/{len(image_files)}]: {image_file.name}")
            try:
                result = await self.infer_image(
                    image_path=str(image_file),
                    output_dir=output_dir,
                    **kwargs,
                )
                results.append(result)
                if result.success:
                    logger.info(f"完成 [{i+1}/{len(image_files)}]: {image_file.name} -> {result.output_path}")
                else:
                    logger.warning(f"失败 [{i+1}/{len(image_files)}]: {image_file.name} - {result.error}")
            except Exception as e:
                logger.error(f"异常 [{i+1}/{len(image_files)}]: {image_file.name} - {e}")
                results.append(RestoreResult(success=False, error=str(e)))

        success_count = sum(1 for r in results if r.success)
        logger.info(f"批量处理完成: {success_count}/{len(results)} 成功")
        return results
