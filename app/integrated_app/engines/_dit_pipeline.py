"""DiT sampling pipeline mixin for SeedVR2Engine.

Extracted from seedvr2_engine.py as part of structural refactoring
(phase 2A). Contains DiT generation step, timestep transform, and
condition building methods.
"""

import logging

import torch

from app.integrated_app.engines._memory_utils import (
    DEFAULT_VAE_SPATIAL_DOWNSAMPLE,
    TEXT_EMBED_DIM,
)

logger = logging.getLogger(__name__)


class _DitPipelineMixin:
    """Mixin: pipeline methods extracted from SeedVR2Engine."""

    def _get_text_embeds(self) -> dict:
        """获取正负文本嵌入张量

        加载预训练的正面和负面文本嵌入，移动到推理设备。
        如果文本嵌入文件不存在，使用零嵌入作为 fallback（仍可推理但无文本引导）。

        Returns:
            dict: 包含 "texts_pos" 和 "texts_neg" 键的字典，
                 值为嵌入张量列表（长度为1，适配 batch 接口）
        """
        if self.pos_emb is not None and self.neg_emb is not None:
            return {
                "texts_pos": [self.pos_emb.to(self.device)],
                "texts_neg": [self.neg_emb.to(self.device)],
            }
        else:
            logger.warning("使用零文本嵌入")
            dummy = torch.zeros(1, TEXT_EMBED_DIM, device=self.device, dtype=torch.float16)
            return {
                "texts_pos": [dummy],
                "texts_neg": [dummy],
            }

    def _get_condition(self, latent: torch.Tensor, latent_blur: torch.Tensor, task: str = "sr") -> torch.Tensor:
        """构建 DiT 条件输入张量

        根据任务类型将低分辨率潜变量与条件标记拼接为模型输入。
        不同任务使用不同的帧作为条件:
        - sr (超分): 所有帧使用模糊潜变量作为条件，最后一通道为 1.0 标记
        - i2v (图像生视频): 仅第一帧使用原始潜变量
        - v2v (视频生视频): 前两帧使用原始潜变量

        Args:
            latent: 原始潜变量张量，形状 T H W C
            latent_blur: 模糊/退化潜变量张量（低分辨率输入），形状 T H W C
            task: 任务类型，"sr"/"i2v"/"v2v"

        Returns:
            torch.Tensor: 条件张量，形状 T H W (C+1)，最后一通道为条件标记

        Raises:
            NotImplementedError: 未知任务类型时抛出
        """
        t, h, w, c = latent.shape
        cond = torch.zeros([t, h, w, c + 1], device=latent.device, dtype=latent.dtype)
        if task == "sr" or t == 1:
            cond[:, ..., :-1] = latent_blur[:]
            cond[:, ..., -1:] = 1.0
            return cond
        if task == "i2v":
            cond[:1, ..., :-1] = latent[:1]
            cond[:1, ..., -1:] = 1.0
            return cond
        if task == "v2v":
            cond[:2, ..., :-1] = latent[:2]
            cond[:2, ..., -1:] = 1.0
            return cond
        raise NotImplementedError(f"未知任务类型: {task}")

    def _timestep_transform(self, timesteps: torch.Tensor, latents_shapes: torch.Tensor) -> torch.Tensor:
        """分辨率自适应时间步变换

        根据输入分辨率和帧数动态调整扩散时间步，使不同分辨率/长度的输入
        都能获得合适的噪声调度。这是高分辨率/长视频生成的关键技巧。

        算法原理:
        - 小分辨率/短帧: shift=1.0，不做变换
        - 大分辨率/长帧: 使用线性函数增大 shift 值，等效于加强早期去噪
        - 图像和视频使用不同的 shift 函数（视频需要更大的 shift）

        Args:
            timesteps: 原始时间步张量
            latents_shapes: 潜变量形状张量 [batch, [t, h, w, c]]

        Returns:
            torch.Tensor: 变换后的时间步张量

        Note:
            此方法对齐 VideoDiffusionInfer.timestep_transform 官方实现，
            如果配置中 timesteps.transform=False 则直接返回原始时间步。
        """
        diff_cfg = self._model_config["diffusion"]
        if not diff_cfg.get("timesteps", {}).get("transform", False):
            return timesteps

        vae_cfg = self._model_config["vae"]
        vt = vae_cfg.get("temporal_downsample_factor", 4)
        vs = DEFAULT_VAE_SPATIAL_DOWNSAMPLE

        frames = (latents_shapes[:, 0] - 1) * vt + 1
        heights = latents_shapes[:, 1] * vs
        widths = latents_shapes[:, 2] * vs

        def get_lin_function(x1, y1, x2, y2):
            m = (y2 - y1) / (x2 - x1)
            b = y1 - m * x1
            return lambda x: m * x + b

        img_shift_fn = get_lin_function(x1=256 * 256, y1=1.0, x2=1024 * 1024, y2=3.2)
        vid_shift_fn = get_lin_function(x1=256 * 256 * 37, y1=1.0, x2=1280 * 720 * 145, y2=5.0)
        shift = torch.where(
            frames > 1,
            vid_shift_fn(heights * widths * frames),
            img_shift_fn(heights * widths),
        )

        timesteps = timesteps / self.schedule.T
        timesteps = shift * timesteps / (1 + (shift - 1) * timesteps)
        timesteps = timesteps * self.schedule.T
        return timesteps

    def _generation_step(
        self,
        cond_latents: list[torch.Tensor],
        text_embeds: dict,
        cfg_scale: float = 7.5,
        cfg_rescale: float = 0.0,
        sample_steps: int = 50,
        seed: int = 42,
        input_noise_scale: float = 0.0,
        latent_noise_scale: float = 0.0,
        restoration_guidance_scale: float = 0.0,
    ) -> list[torch.Tensor]:
        """DiT 采样步骤

        支持两种模式:
        - 标准模式 (cfg_scale=7.5, steps=50): 50步 Euler 采样 + CFG
        - 蒸馏模式 (cfg_scale=1.0, steps=1): 单步推理 + 噪声增强

        关键: 采样前必须对 timesteps 应用 timestep_transform (分辨率自适应偏移)
        """
        from model_lib.dit_v2 import na

        # 更新 CFG 和采样步数，重新配置扩散组件
        diff_cfg = self._model_config["diffusion"]
        diff_cfg["cfg"]["scale"] = cfg_scale
        diff_cfg["cfg"]["rescale"] = cfg_rescale
        diff_cfg["timesteps"]["sampling"]["steps"] = sample_steps
        self._configure_diffusion(self._model_config, self.device)

        # 设置随机种子
        torch.manual_seed(seed)

        # 生成噪声
        noises = [torch.randn_like(latent) for latent in cond_latents]
        logger.info(f"噪声形状: {noises[0].size()}, cfg_scale={cfg_scale}, steps={sample_steps}")

        is_distilled = sample_steps == 1 and cfg_scale == 1.0

        # 噪声增强: 严格对齐 ComfyUI 工作流
        # ComfyUI 中 latent_noise_scale 默认为 0.0 (不加噪声到条件)
        # aug_noises 仅在 latent_noise_scale > 0 时才有意义
        if is_distilled and latent_noise_scale > 0:
            aug_noises = [base * 0.1 + torch.randn_like(base) * 0.05 for base in noises]
            cond_noise_scale = latent_noise_scale
        else:
            # 默认路径: 不对条件添加噪声 (与 ComfyUI 工作流一致)
            aug_noises = [torch.zeros_like(n) for n in noises]
            cond_noise_scale = 0.0

        def _add_noise(x, aug_noise):
            if cond_noise_scale <= 0:
                return x
            t = torch.tensor([1000.0], device=self.device) * cond_noise_scale
            shape = torch.tensor(x.shape, device=self.device)[None]  # 包含 T 维度
            t = self._timestep_transform(t, shape)
            x = self.schedule.forward(x, aug_noise, t)
            return x

        # 构建条件
        conditions = [
            self._get_condition(
                noise,
                task="sr",
                latent_blur=_add_noise(latent_blur, aug_noise),
            )
            for noise, aug_noise, latent_blur in zip(noises, aug_noises, cond_latents, strict=False)
        ]

        # 文本嵌入
        texts_pos = text_embeds["texts_pos"]
        texts_neg = text_embeds["texts_neg"]

        # Flatten
        text_pos_embeds, text_pos_shapes = na.flatten(texts_pos)
        text_neg_embeds, text_neg_shapes = na.flatten(texts_neg)
        latents, latents_shapes = na.flatten(noises)
        latents_cond, _ = na.flatten(conditions)

        batch_size = len(noises)

        # ===== 关键: 对采样时间步应用 timestep_transform =====
        # 与 test_e2e.py 一致: 在采样前替换 sampler 的 timesteps
        original_timesteps = self.sampler.timesteps.timesteps
        raw_timesteps = self.sampling_timesteps.timesteps
        # latents_shapes[0] 是第一个样本的形状 [t, h, w, c]
        first_latent_shape = torch.tensor(noises[0].shape, device=self.device)
        transformed_timesteps = self._timestep_transform(raw_timesteps, first_latent_shape.unsqueeze(0))
        self.sampler.timesteps.timesteps = transformed_timesteps
        logger.info(
            f"timestep_transform 已应用, timesteps 范围: [{transformed_timesteps.min():.1f}, {transformed_timesteps.max():.1f}]"
        )

        # 采样
        self.dit.eval()

        # 初始化采样增强模块
        _restoration_sampler = None
        _dynamic_cfg = None
        if restoration_guidance_scale > 0:
            from app.integrated_app.optimization.inference.diffusion_sampling import (
                RestorationGuidanceConfig,
                RestorationGuidedSampling,
            )

            _restoration_sampler = RestorationGuidedSampling(
                RestorationGuidanceConfig(
                    enabled=True,
                    guidance_scale=restoration_guidance_scale,
                    timestep_decay=True,
                    decay_type="cosine",
                    decay_start_ratio=0.3,
                )
            )

        # 动态 CFG: 从配置读取是否启用
        dynamic_cfg_enabled = self.config.get("inference", {}).get("dynamic_cfg", False)
        if dynamic_cfg_enabled and cfg_scale > 1.0:
            from app.integrated_app.optimization.inference.diffusion_sampling import DynamicCFG

            _dynamic_cfg = DynamicCFG(initial_scale=cfg_scale * 0.5, final_scale=cfg_scale)

        try:
            with torch.no_grad(), torch.autocast("cuda", torch.bfloat16, enabled=(self.device == "cuda")):
                total_steps = len(self.sampler.timesteps.timesteps)
                latents = self.sampler.sample(
                    x=latents,
                    f=lambda args: self._guided_generation_step(
                        args=args,
                        latents_cond=latents_cond,
                        text_pos_embeds=text_pos_embeds,
                        text_neg_embeds=text_neg_embeds,
                        text_pos_shapes=text_pos_shapes,
                        text_neg_shapes=text_neg_shapes,
                        latents_shapes=latents_shapes,
                        batch_size=batch_size,
                        cfg_scale=(
                            _dynamic_cfg.get_scale(args.i, total_steps)
                            if _dynamic_cfg is not None
                            else (cfg_scale if (args.i + 1) / total_steps <= diff_cfg["cfg"].get("partial", 1) else 1.0)
                        ),
                        cfg_rescale=cfg_rescale,
                        restoration_guidance_scale=restoration_guidance_scale,
                        current_noisy=latents_cond,  # 使用原始条件 latent 而非初始噪声
                        restoration_sampler=_restoration_sampler,
                        current_step=args.i,
                        total_steps=total_steps,
                    ),
                )
        finally:
            # 恢复原始 timesteps
            self.sampler.timesteps.timesteps = original_timesteps

        # Unflatten
        latents = na.unflatten(latents, latents_shapes)
        return latents

    def _guided_generation_step(
        self,
        args,
        latents_cond: torch.Tensor,
        text_pos_embeds: torch.Tensor,
        text_neg_embeds: torch.Tensor,
        text_pos_shapes: list,
        text_neg_shapes: list,
        latents_shapes: list,
        batch_size: int,
        cfg_scale: float,
        cfg_rescale: float,
        restoration_guidance_scale: float,
        current_noisy: torch.Tensor,
        restoration_sampler=None,
        current_step: int = 0,
        total_steps: int = 1,
    ) -> torch.Tensor:
        """带 Restoration Guidance 的 DiT 生成步 (Vivid-VR inspired)

        在标准 CFG 基础上，额外约束输出与退化输入的一致性，
        使修复结果在保真度和真实感之间取得平衡。
        支持时间步衰减、cfg_rescale 稳定性增强和动态 CFG。

        当 restoration_guidance_scale == 0 时退化为标准 CFG，无额外开销。
        """
        from common.diffusion import classifier_free_guidance_dispatcher

        # 计算标准 CFG 结果
        # 对齐 ComfyUI: pos/neg 均以惰性 lambda 传入 dispatcher，
        # cfg_scale==1.0 时 dispatcher 短路只执行 pos，不执行 neg forward (节省约 2 倍蒸馏推理时间)
        def _pos_forward():
            return self.dit(
                vid=torch.cat([args.x_t, latents_cond], dim=-1),
                txt=text_pos_embeds,
                vid_shape=latents_shapes,
                txt_shape=text_pos_shapes,
                timestep=args.t.repeat(batch_size),
            ).vid_sample

        def _neg_forward():
            return self.dit(
                vid=torch.cat([args.x_t, latents_cond], dim=-1),
                txt=text_neg_embeds,
                vid_shape=latents_shapes,
                txt_shape=text_neg_shapes,
                timestep=args.t.repeat(batch_size),
            ).vid_sample

        cfg_result = classifier_free_guidance_dispatcher(
            pos=_pos_forward,
            neg=_neg_forward,
            scale=cfg_scale,
            rescale=cfg_rescale,
        )

        # 应用 cfg_rescale 稳定性增强 (VEnhancer inspired)
        if cfg_rescale > 0:
            from app.integrated_app.optimization.inference.diffusion_sampling import (
                apply_cfg_rescale as apply_cfg_rescale_fn,
            )

            # scale==1.0 时 cfg_result 即 pos 输出，比值恒为 1.0，无副作用
            cfg_result = apply_cfg_rescale_fn(cfg_result, cfg_result, rescale_factor=cfg_rescale)

        # Restoration Guidance (Vivid-VR inspired) 带时间步衰减
        effective_restoration_scale = restoration_guidance_scale
        if restoration_sampler is not None and restoration_guidance_scale > 0:
            effective_restoration_scale = restoration_sampler.compute_guidance_scale(
                base_cfg_scale=1.0,
                current_step=current_step,
                total_steps=total_steps,
            )

        if effective_restoration_scale > 0:
            # 应用 Restoration Guidance: 将 CFG 结果向原始输入方向偏移
            # fidelity_direction = original_condition - current_noisy
            # current_noisy 为条件张量 (含 C+1 条件标记通道)，与 x_t 通道数不同，
            # 需裁掉标记通道后与当前噪声潜变量对齐
            c = args.x_t.shape[-1]
            fidelity_direction = current_noisy[..., :c] - args.x_t
            guided_result = cfg_result + effective_restoration_scale * fidelity_direction
            return guided_result

        # 标准 CFG (无 restoration guidance)
        return cfg_result

    # ------------------------------------------------------------------
    # 内部方法 - 视频处理辅助
    # ------------------------------------------------------------------
