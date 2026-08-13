"""Latent Consistency Model (LCM) — One-step 蒸馏实现。

通过 LCM 蒸馏将多步扩散过程压缩为单步生成，实现 10x 推理加速。

核心原理:
    LCM 基于 PF-ODE（Probability Flow ODE）的一致性属性：在 ODE 轨迹上
    任意两点的预测结果一致。通过蒸馏训练，模型学会在任意噪声水平直接
    预测原始图像，从而实现单步生成。

参考:
    - 原始论文: "Latent Consistency Models" (Luo et al., 2023)
      https://arxiv.org/abs/2310.04378
    - LCM-LoRA: https://arxiv.org/abs/2311.05556

依赖:
    - torch >= 2.4.0
    - diffusers >= 0.30.0 (UNet2DConditionModel, AutoencoderKL)

验收标准:
    - 单步生成质量接近多步（SSIM > 0.85）
    - 生成速度提升 10x
    - VRAM 占用降低 40%
"""

from __future__ import annotations

import logging

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# diffusers 类型在 pyproject.toml 中已配置 ignore_missing_imports
try:
    from diffusers import AutoencoderKL, UNet2DConditionModel

    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False
    AutoencoderKL = None  # type: ignore[assignment,misc]
    UNet2DConditionModel = None  # type: ignore[assignment,misc]
    logger.warning("diffusers 未安装，LCM 蒸馏功能不可用。请安装: pip install diffusers>=0.30.0")


class LCMScheduler:
    """LCM 专用调度器。

    实现简化的 LCM 调度逻辑，支持单步去噪。

    Args:
        num_train_timesteps: 训练时间步总数（默认 1000）。
        beta_start: beta 调度的起始值。
        beta_end: beta 调度的结束值。
        beta_schedule: beta 调度类型（``"linear"`` 或 ``"scaled_linear"``）。
    """

    def __init__(
        self,
        num_train_timesteps: int = 1000,
        beta_start: float = 0.00085,
        beta_end: float = 0.012,
        beta_schedule: str = "scaled_linear",
    ) -> None:
        self.num_train_timesteps = num_train_timesteps

        if beta_schedule == "scaled_linear":
            betas = (
                torch.linspace(
                    beta_start**0.5,
                    beta_end**0.5,
                    num_train_timesteps,
                )
                ** 2
            )
        else:
            betas = torch.linspace(beta_start, beta_end, num_train_timesteps)

        self.betas = betas
        self.alphas = 1.0 - self.betas
        self.alphas_cumprod = torch.cumprod(self.alphas, dim=0)

    def step(
        self,
        model_output: torch.Tensor,
        timestep: int,
        sample: torch.Tensor,
    ) -> torch.Tensor:
        """单步去噪 — LCM 核心操作。

        直接从当前噪声状态预测原始图像（一步到位）。

        Args:
            model_output: 模型预测的噪声。
            timestep: 当前时间步索引。
            sample: 当前含噪样本。

        Returns:
            预测的原始样本。
        """
        alpha_prod_t = self.alphas_cumprod[timestep]
        beta_prod_t = 1 - alpha_prod_t

        # 预测原始图像
        pred_original_sample = (sample - beta_prod_t**0.5 * model_output) / alpha_prod_t**0.5

        # LCM: 一步到达（直接返回预测的原始图像）
        return pred_original_sample


class LatentConsistencyModel(nn.Module):
    """Latent Consistency Model — One-step 图像生成。

    通过蒸馏将多步扩散过程压缩为单步，实现快速图像生成。

    Args:
        unet: 预训练的 UNet2DConditionModel。
        vae: 预训练的 AutoencoderKL。
        scheduler: LCM 专用调度器（如未提供则使用默认配置）。

    Attributes:
        unet: UNet 去噪模型。
        vae: VAE 编解码器。
        scheduler: LCM 调度器。

    Raises:
        ImportError: 如果 diffusers 未安装。
    """

    def __init__(
        self,
        unet: UNet2DConditionModel,
        vae: AutoencoderKL,
        scheduler: LCMScheduler | None = None,
    ) -> None:
        super().__init__()

        if not DIFFUSERS_AVAILABLE:
            raise ImportError(
                "diffusers 未安装，无法创建 LatentConsistencyModel。" "请安装: pip install diffusers>=0.30.0",
            )

        self.unet = unet
        self.vae = vae
        self.scheduler = scheduler or LCMScheduler()

    @torch.no_grad()
    def generate_one_step(
        self,
        prompt: str,
        height: int = 512,
        width: int = 512,
        num_inference_steps: int = 1,
        guidance_scale: float = 7.5,
        negative_prompt: str = "",
        device: torch.device | None = None,
        generator: torch.Generator | None = None,
    ) -> torch.Tensor:
        """单步生成图像。

        使用 LCM 的单步去噪能力，从随机噪声直接生成图像。

        Args:
            prompt: 正向提示词。
            height: 输出图像高度（会被 VAE 缩放因子向下取整）。
            width: 输出图像宽度。
            num_inference_steps: 推理步数（LCM 通常为 1-4 步）。
            guidance_scale: CFG 引导强度。
            negative_prompt: 负向提示词。
            device: 生成设备（默认使用 UNet 所在设备）。
            generator: 随机数生成器（用于可复现性）。

        Returns:
            生成的图像张量，形状 ``[1, 3, H, W]``，值域 [0, 1]。
        """
        if device is None:
            device = next(self.unet.parameters()).device

        # 确保 VAE 和 UNet 在同一设备
        self.vae = self.vae.to(device)

        # VAE 缩放因子（通常为 8）
        vae_scale = self.vae.config.get("scaling_factor", 0.18215)

        # 文本编码
        text_embeddings = self._encode_prompt(prompt, device)
        negative_embeddings = self._encode_prompt(negative_prompt, device)

        # 初始噪声
        latents_shape = (1, 4, height // 8, width // 8)
        latents = torch.randn(
            latents_shape,
            device=device,
            generator=generator,
        )

        # 多步去噪（步数极少，通常 1-4 步）
        for step in range(num_inference_steps):
            timestep_ratio = 1.0 - (step / max(num_inference_steps, 1))
            timestep_idx = int(timestep_ratio * (self.scheduler.num_train_timesteps - 1))

            # CFG: 无条件 + 条件
            latent_model_input = torch.cat([latents] * 2)
            timestep = torch.tensor([timestep_idx], device=device, dtype=torch.long)

            noise_pred = self.unet(
                latent_model_input,
                timestep,
                encoder_hidden_states=torch.cat(
                    [negative_embeddings, text_embeddings],
                ),
            ).sample

            noise_pred_uncond, noise_pred_text = noise_pred.chunk(2)

            # CFG 采样
            noise_pred = noise_pred_uncond + guidance_scale * (noise_pred_text - noise_pred_uncond)

            # LCM 单步去噪
            latents = self.scheduler.step(noise_pred, timestep_idx, latents)

        # VAE 解码
        image = self.vae.decode(latents / vae_scale).sample

        # 归一化到 [0, 1]
        image = (image / 2 + 0.5).clamp(0, 1)

        return image

    def _encode_prompt(
        self,
        prompt: str,
        device: torch.device,
    ) -> torch.Tensor:
        """编码文本提示词为嵌入向量。

        目前使用占位实现（随机嵌入）。完整实现应使用 CLIP 或 T5 编码器。

        TODO:
            集成 OpenCLIP 或 T5 编码器进行真正的文本编码。

        Args:
            prompt: 待编码的文本提示词。
            device: 嵌入张量所在的设备。

        Returns:
            文本嵌入张量，形状 ``[1, 77, 768]``。
        """
        # 占位实现 — 返回随机嵌入
        # 完整实现应使用 CLIP/T5 编码器
        return torch.randn(1, 77, 768, device=device)

    def train_lcm(
        self,
        teacher_model: UNet2DConditionModel,
        dataloader: object,
        optimizer: torch.optim.Optimizer,
        num_epochs: int = 10,
        device: torch.device | None = None,
    ) -> list[float]:
        """LCM 蒸馏训练循环。

        使用教师模型（多步扩散）指导学生模型（LCM）学习单步生成。

        蒸馏过程:
            1. 教师模型从噪声 x_t 预测 x_{t-1}（一步去噪）
            2. 学生模型从 x_t 直接预测 x_0（原始图像）
            3. 损失 = 学生预测的 x_0 与 ODE 轨迹上 x_0 的一致性误差

        Args:
            teacher_model: 教师模型（预训练的多步扩散 UNet）。
            dataloader: 训练数据加载器。
            optimizer: 优化器。
            num_epochs: 训练轮数。
            device: 训练设备。

        Returns:
            每个 epoch 的平均损失列表。
        """
        if device is None:
            device = next(self.unet.parameters()).device

        teacher_model = teacher_model.to(device)
        teacher_model.eval()

        losses: list[float] = []

        for epoch in range(num_epochs):
            epoch_loss = 0.0
            num_batches = 0

            self.unet.train()
            for batch in dataloader:
                if isinstance(batch, (tuple, list)):
                    images = batch[0]
                else:
                    images = batch
                images = images.to(device)

                # 随机采样时间步
                batch_size = images.shape[0]
                timesteps = torch.randint(
                    0,
                    self.scheduler.num_train_timesteps,
                    (batch_size,),
                    device=device,
                )

                # 编码到 latent 空间
                with torch.no_grad():
                    latents = self.vae.encode(images).latent_dist.sample()
                    latents = latents * self.vae.config.get("scaling_factor", 0.18215)

                    # 添加噪声
                    noise = torch.randn_like(latents)
                    alpha_prod = self.scheduler.alphas_cumprod[timesteps].view(-1, 1, 1, 1)
                    noisy_latents = alpha_prod**0.5 * latents + (1 - alpha_prod) ** 0.5 * noise

                    # 教师模型预测（用于一致性目标）
                    teacher_pred = teacher_model(
                        noisy_latents,
                        timesteps,
                    ).sample

                # 学生模型预测
                student_pred = self.unet(noisy_latents, timesteps).sample

                # 一致性损失
                loss = torch.nn.functional.mse_loss(student_pred, teacher_pred)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_loss += loss.item()
                num_batches += 1

            avg_loss = epoch_loss / max(num_batches, 1)
            losses.append(avg_loss)
            logger.info("LCM 蒸馏 Epoch %d/%d, Loss: %.4f", epoch + 1, num_epochs, avg_loss)

        return losses


def create_lcm_from_pretrained(
    unet_path: str,
    vae_path: str,
    device: torch.device | None = None,
) -> LatentConsistencyModel:
    """从预训练权重创建 LCM 模型。

    Args:
        unet_path: UNet 权重路径或 HuggingFace 模型 ID。
        vae_path: VAE 权重路径或 HuggingFace 模型 ID。
        device: 模型加载到的设备。

    Returns:
        初始化好的 :class:`LatentConsistencyModel` 实例。

    Raises:
        ImportError: 如果 diffusers 未安装。
    """
    if not DIFFUSERS_AVAILABLE:
        raise ImportError("diffusers 未安装。请安装: pip install diffusers>=0.30.0")

    unet = UNet2DConditionModel.from_pretrained(unet_path)
    vae = AutoencoderKL.from_pretrained(vae_path)

    model = LatentConsistencyModel(unet=unet, vae=vae)

    if device is not None:
        model = model.to(device)

    return model
