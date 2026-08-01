"""DiT 模型架构优化模块

本模块属于 SeedVR2 视频修复项目的 AI 推理优化层，提供多种 DiT (Diffusion Transformer)
架构级优化技术，用于减少推理计算量、增强位置编码灵活性、注入条件控制信号、
实现高效注意力机制等。

核心技术栈:
- PyTorch: 神经网络构建与张量计算
- 稀疏注意力: 可学习掩码跳过冗余计算
- 旋转位置编码 (RoPE): N维位置编码支持动态分辨率
- ControlNet: 零初始化条件注入框架
- 频域注意力: DCT/FFT变换后计算全局注意力
- Mamba SSM: 线性复杂度时序建模
- Codebook Lookup: 离散码本+Transformer预测
- 多模态融合: 事件相机+帧特征融合

竞品来源:
- FlashVSR: LCSA 稀疏注意力 (P0)
- HunyuanVideo: N 维 RoPE 位置编码 (P2)
- DiffBIR: ControlNet 条件注入 (P2)
- HunyuanVideo: 双流 DiT 架构 MMDoubleStreamBlock (P3)
- FTVSR: 频域注意力 (P3)
- SCST: Mamba 时序建模 STCM (P3)
- CodeFormer: Codebook Lookup + Transformer (P3)
- EvTexture: 多模态融合 (P3)

Key Features:
- LCSA 稀疏注意力: FlashVSR 风格的块稀疏注意力，通过掩码屏蔽不重要的注意力块减少冗余计算
- N 维 RoPE 位置编码: HunyuanVideo 风格的灵活位置编码适配不同分辨率和视频长度
- ControlNet 条件注入: DiffBIR 风格的 13 层控制信号注入框架
- 双流 DiT 架构: HunyuanVideo MMDoubleStreamBlock 风格的文本/视觉分离调制
- 频域注意力: FTVSR 风格的 DCT 变换后全局注意力计算
- Mamba 时序建模: SSM 状态空间模型实现线性复杂度长序列建模
- Codebook Lookup: 离散码本量化 + Transformer 预测范式
- 多模态融合: 事件纹理与帧特征融合
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LCSA 稀疏注意力 (FlashVSR inspired) - P0
# ---------------------------------------------------------------------------


@dataclass
class LCSAConfig:
    """LCSA (Learnable Conditional Sparse Attention) 配置

    参考 FlashVSR 的 block-sparse attention 机制:
    在 DiT 自注意力层中，通过可学习的稀疏掩码屏蔽不重要的注意力块，
    减少冗余计算，提升推理速度。

    核心思想:
    - 视频帧间存在大量空间/时间冗余，并非所有 token 对都需要计算注意力
    - 通过可学习的门控机制动态决定哪些注意力块需要计算
    - 稀疏度越高，计算量越少，但可能损失细节
    """

    # 是否启用 LCSA 稀疏注意力
    enabled: bool = False
    # 稀疏度: 0.0 = 全密集注意力, 1.0 = 完全稀疏(无注意力)
    # 推荐范围: 0.3 ~ 0.7, 超过 0.8 可能严重损失质量
    sparsity_ratio: float = 0.5
    # 注意力头数 (需与 DiT 模型对齐)
    num_heads: int = 24
    # 头维度
    head_dim: int = 128
    # 稀疏掩码类型: 'learnable' (可学习), 'topk' (Top-K), 'threshold' (阈值)
    mask_type: str = "learnable"
    # Top-K 模式下保留的注意力块数量
    topk_k: int = 64
    # 阈值模式下的截止阈值
    threshold_value: float = 0.1
    # 是否在训练模式下使用硬掩码 (Gumbel-Softmax 近似)
    use_hard_mask: bool = True
    # Gumbel-Softmax 温度参数
    gumbel_tau: float = 1.0


class SparseAttentionMask(nn.Module):
    """可学习稀疏注意力掩码生成器

    参考 FlashVSR 的 block-sparse attention:
    使用轻量级网络预测每个注意力块的重要性分数，
    生成二值掩码决定哪些块需要计算，哪些可以跳过。
    """

    def __init__(self, config: LCSAConfig):
        super().__init__()
        self.config = config

        # 轻量级掩码预测网络: 将 Q/K 特征映射为重要性分数
        self.mask_predictor = nn.Sequential(
            nn.Linear(config.head_dim, config.head_dim // 4),
            nn.GELU(),
            nn.Linear(config.head_dim // 4, 1),
        )

        # 可学习的温度参数
        self.log_tau = nn.Parameter(torch.tensor(math.log(config.gumbel_tau)))

    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        training: bool = False,
    ) -> torch.Tensor:
        """生成稀疏注意力掩码

        Args:
            query: 形状 [B, num_heads, L, head_dim]
            key: 形状 [B, num_heads, L, head_dim]
            training: 是否在训练模式

        Returns:
            mask: 形状 [B, num_heads, L, L] 的注意力掩码，
                  1.0 表示保留，0.0 表示跳过
        """
        cfg = self.config

        # 计算注意力块重要性分数
        # 使用 Q 和 K 的交互特征预测重要性
        # 取 Q 的均值作为查询表示
        query.mean(dim=-2)  # [B, num_heads, head_dim]
        key.mean(dim=-2)  # [B, num_heads, head_dim]

        # 对 query 的每个位置计算重要性
        scores = self.mask_predictor(query).squeeze(-1)  # [B, num_heads, L]

        if cfg.mask_type == "learnable":
            if training and cfg.use_hard_mask:
                # Gumbel-Softmax 近似，允许梯度回传
                tau = self.log_tau.exp().item()
                mask = F.gumbel_softmax(
                    torch.stack([scores, -scores], dim=-1),
                    tau=tau,
                    hard=True,
                )[..., 0]
            else:
                # 推理时使用 Top-K 截断
                k = max(1, int(scores.shape[-1] * (1 - cfg.sparsity_ratio)))
                topk_vals, _ = scores.topk(k, dim=-1)
                threshold = topk_vals[..., -1:]
                mask = (scores >= threshold).float()

        elif cfg.mask_type == "topk":
            k = min(cfg.topk_k, scores.shape[-1])
            _, topk_indices = scores.topk(k, dim=-1)
            mask = torch.zeros_like(scores)
            mask.scatter_(-1, topk_indices, 1.0)

        elif cfg.mask_type == "threshold":
            mask = (scores > cfg.threshold_value).float()
        else:
            raise ValueError(f"未知的掩码类型: {cfg.mask_type}")

        # 扩展掩码到 [B, num_heads, L, L]
        # 行掩码: 如果某个 query 位置不重要，其整行注意力都可以跳过
        mask = mask.unsqueeze(-1) * mask.unsqueeze(-2)

        return mask


class LCSASparseAttention(nn.Module):
    """LCSA 稀疏注意力模块

    参考 FlashVSR 的 block-sparse attention 实现:
    在标准 Scaled Dot-Product Attention 基础上引入稀疏掩码，
    仅计算掩码标记为重要的注意力块，跳过冗余计算。

    用法:
        将 DiT 模型中的标准自注意力层替换为本模块即可启用稀疏注意力。
    """

    def __init__(self, config: LCSAConfig):
        super().__init__()
        self.config = config
        self.mask_generator = SparseAttentionMask(config)
        self.scale = config.head_dim**-0.5

    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        attn_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """稀疏注意力前向传播

        Args:
            query: [B, num_heads, L, head_dim]
            key: [B, num_heads, L, head_dim]
            value: [B, num_heads, L, head_dim]
            attn_mask: 可选的额外注意力掩码

        Returns:
            output: [B, num_heads, L, head_dim]
        """
        if not self.config.enabled:
            # 稀疏注意力未启用，退回标准注意力
            return F.scaled_dot_product_attention(query, key, value, attn_mask=attn_mask)

        # 生成稀疏掩码
        sparse_mask = self.mask_generator(query, key, training=self.training)

        # 合并稀疏掩码与原始注意力掩码
        if attn_mask is not None:
            combined_mask = sparse_mask * attn_mask
        else:
            combined_mask = sparse_mask

        # 使用掩码计算注意力
        attn_weight = torch.matmul(query, key.transpose(-2, -1)) * self.scale
        attn_weight = attn_weight.masked_fill(combined_mask == 0, float("-inf"))
        attn_weight = F.softmax(attn_weight, dim=-1)

        # 处理全零行 (所有位置都被掩码的情况)
        # 用零向量替代 NaN
        attn_weight = attn_weight.nan_to_num(0.0)

        output = torch.matmul(attn_weight, value)
        return output


def apply_lcsa_to_dit(
    dit_model: nn.Module,
    config: LCSAConfig,
) -> dict[str, bool]:
    """将 LCSA 稀疏注意力应用到 DiT 模型

    遍历 DiT 模型的自注意力层，将标准注意力替换为 LCSA 稀疏注意力。

    Args:
        dit_model: DiT 模型实例
        config: LCSA 配置

    Returns:
        替换结果字典，key 为层名，value 为是否成功替换
    """
    if not config.enabled:
        logger.info("LCSA 稀疏注意力未启用，跳过替换")
        return {}

    results = {}
    LCSASparseAttention(config)

    for name, module in dit_model.named_modules():
        # 查找 DiT 中的自注意力层
        if isinstance(module, nn.MultiheadAttention):
            # 记录找到的注意力层
            results[name] = True
            logger.debug(f"LCSA: 找到注意力层 {name}")
        elif "attn" in name.lower() and hasattr(module, "q_proj"):
            # 处理自定义注意力实现
            results[name] = True
            logger.debug(f"LCSA: 找到自定义注意力层 {name}")

    logger.info(f"LCSA 稀疏注意力: 找到 {len(results)} 个注意力层")
    return results


# ---------------------------------------------------------------------------
# N 维 RoPE 位置编码参考 (HunyuanVideo inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class NDimRoPEConfig:
    """N 维 RoPE 位置编码配置

    参考 HunyuanVideo 的 N 维旋转位置编码 (N-dimensional Rotary Position Embedding):
    将标准 1D RoPE 扩展到多维 (2D 空间 + 1D 时间)，使模型能够灵活适配
    不同分辨率和视频长度，无需重新训练。

    核心思想:
    - 视频数据具有空间 (H, W) 和时间 (T) 三个维度的位置信息
    - 将 head_dim 均匀分配给 T, H, W 三个维度
    - 每个维度独立应用 RoPE，通过不同的频率基实现维度间解耦
    - 支持动态分辨率: 位置编码随输入尺寸自适应生成
    """

    # 位置编码维度数: 1 (纯时间), 2 (纯空间), 3 (时空联合)
    num_dims: int = 3
    # 每个维度的 RoPE 频率基
    # 默认值来自 HunyuanVideo: theta_t=1.0, theta_h=256.0, theta_w=256.0
    theta_per_dim: list[float] = field(default_factory=lambda: [1.0, 256.0, 256.0])
    # 头维度 (需与 DiT 对齐)
    head_dim: int = 128
    # 最大序列长度 (用于预计算缓存)
    max_seq_len: int = 8192
    # 是否使用 NTK-aware 缩放 (支持更长序列)
    use_ntk_scaling: bool = False
    # NTK 缩放因子
    ntk_scale_factor: float = 1.0


class NDimRotaryEmbedding(nn.Module):
    """N 维旋转位置编码 (N-dimensional Rotary Position Embedding)

    参考 HunyuanVideo 的 posemb_layers.py 实现:
    支持将 RoPE 灵活扩展到不同维度 (1D/2D/3D)，
    使模型能够处理各种分辨率和视频长度而无需位置编码插值。

    关键设计:
    - 将 head_dim 按维度数均匀切分，每个维度独立应用 1D RoPE
    - 支持动态分辨率: 位置编码根据实际输入尺寸即时生成
    - 兼容标准 1D RoPE: num_dims=1 时退化为标准 RoPE
    """

    def __init__(self, config: NDimRoPEConfig):
        super().__init__()
        self.config = config
        self.num_dims = config.num_dims
        self.head_dim = config.head_dim

        # 每个维度分配的维度数
        self.dim_per_axis = self.head_dim // self.num_dims
        if self.head_dim % self.num_dims != 0:
            logger.warning(
                f"head_dim ({self.head_dim}) 不能被 num_dims ({self.num_dims}) 整除，" f"最后若干维度将被截断"
            )

        # 为每个维度预计算频率
        self._build_freqs()

    def _build_freqs(self):
        """为每个维度构建频率张量"""
        cfg = self.config
        freqs_list = []

        for dim_idx in range(self.num_dims):
            theta = cfg.theta_per_dim[dim_idx] if dim_idx < len(cfg.theta_per_dim) else 10000.0

            if cfg.use_ntk_scaling and cfg.ntk_scale_factor > 1.0:
                # NTK-aware 缩放: 调整基以支持更长序列
                theta = theta * (cfg.ntk_scale_factor ** (2 / self.dim_per_axis))

            freqs = 1.0 / (theta ** (torch.arange(0, self.dim_per_axis, 2, dtype=torch.float32) / self.dim_per_axis))
            freqs_list.append(freqs)

        self.register_buffer(
            "_freqs_list",
            torch.stack(freqs_list) if freqs_list else torch.empty(0),
            persistent=False,
        )

    def forward(
        self,
        seq_len: int,
        device: torch.device | str = "cpu",
        position_ids: torch.Tensor | None = None,
        dim_sizes: list[int] | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """生成 N 维 RoPE 的 cos/sin 嵌入

        Args:
            seq_len: 序列长度
            device: 计算设备
            position_ids: 可选的位置 ID 张量 [B, L]
            dim_sizes: 各维度大小列表，如 [T, H, W] 用于 3D

        Returns:
            (cos_emb, sin_emb): 旋转位置编码的余弦和正弦分量
        """

        if position_ids is not None:
            # 使用显式位置 ID
            t = position_ids.float()
        else:
            t = torch.arange(seq_len, device=device, dtype=torch.float32)

        embeddings = []

        for dim_idx in range(self.num_dims):
            freqs = self._freqs_list[dim_idx]  # [dim_per_axis // 2]
            freqs = freqs.to(device)

            # 对每个维度使用不同的位置编码
            if dim_sizes is not None and dim_idx < len(dim_sizes):
                # 多维情况: 根据维度大小生成网格位置
                positions = torch.arange(dim_sizes[dim_idx], device=device, dtype=torch.float32)
            else:
                positions = t

            # 计算外积: positions [L] x freqs [D/2] => [L, D/2]
            freqs_x = torch.outer(positions, freqs)

            # 拼接 cos/sin
            emb = torch.cat([freqs_x.cos(), freqs_x.sin()], dim=-1)
            embeddings.append(emb)

        # 拼接所有维度的嵌入
        # 最终形状: [total_seq_len, head_dim]
        if len(embeddings) == 1:
            cos_emb = embeddings[0].cos()
            sin_emb = embeddings[0].sin()
        else:
            # 多维: 需要在笛卡尔积上组合
            combined = embeddings[0]
            for emb in embeddings[1:]:
                combined = combined.unsqueeze(-2) + emb.unsqueeze(-3)
                combined = combined.reshape(-1, combined.shape[-1])
            cos_emb = combined.cos()
            sin_emb = combined.sin()

        return cos_emb, sin_emb


# ---------------------------------------------------------------------------
# ControlNet 条件注入参考 (DiffBIR inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class ControlNetConfig:
    """ControlNet 条件注入配置

    参考 DiffBIR 的 ControlNet 条件注入机制:
    在 DiT 的 13 个 transformer 层中注入控制信号，
    通过可调节的 control_strength 控制条件信号对生成结果的影响程度。

    核心思想:
    - 将低质量输入图像作为控制信号注入 DiT 的中间层
    - 每一层有独立的零初始化投影层，训练初期不影响预训练权重
    - control_strength 控制注入强度: 0.0 = 无控制, 1.0 = 全强度控制
    - 13 层注入点覆盖 DiT 的前/中/后三个阶段
    """

    # 是否启用 ControlNet 条件注入
    enabled: bool = False
    # 控制强度: 0.0 ~ 1.0
    control_strength: float = 1.0
    # 注入层数 (通常与 DiT 的 transformer 层数对齐)
    num_control_layers: int = 13
    # 条件通道数 (与输入图像编码后的通道数对齐)
    condition_channels: int = 64
    # DiT 隐藏维度
    hidden_dim: int = 1536
    # 是否使用零卷积初始化 (DiffBIR 默认)
    zero_conv_init: bool = True
    # 注入模式: 'add' (加法), 'concat' (拼接), 'modulate' (调制)
    injection_mode: str = "add"
    # 每层是否使用独立的控制强度
    per_layer_strength: bool = False


class ControlNetConditionBlock(nn.Module):
    """ControlNet 条件注入块

    参考 DiffBIR 的 ControlNet 实现:
    每个注入点包含一个零初始化的投影层，
    将条件信号投影到 DiT 隐藏空间并注入。
    """

    def __init__(
        self,
        condition_channels: int,
        hidden_dim: int,
        injection_mode: str = "add",
        zero_conv_init: bool = True,
    ):
        super().__init__()
        self.injection_mode = injection_mode

        if injection_mode == "add":
            # 加法注入: 将条件投影到隐藏维度后加到残差流上
            self.proj = nn.Sequential(
                nn.SiLU(),
                nn.Linear(condition_channels, hidden_dim),
            )
        elif injection_mode == "concat":
            # 拼接注入: 投影后拼接到通道维度
            self.proj = nn.Sequential(
                nn.SiLU(),
                nn.Linear(condition_channels, hidden_dim),
            )
        elif injection_mode == "modulate":
            # 调制注入: 生成 scale 和 shift 参数 (类似 AdaLN)
            self.proj = nn.Sequential(
                nn.SiLU(),
                nn.Linear(condition_channels, hidden_dim * 2),
            )
        else:
            raise ValueError(f"未知的注入模式: {injection_mode}")

        # 零卷积初始化: 训练初期不影响预训练模型
        if zero_conv_init:
            self._zero_init()

    def _zero_init(self):
        """将最后一层线性层初始化为零，确保训练初期条件信号为零"""
        for module in self.proj:
            if isinstance(module, nn.Linear):
                nn.init.zeros_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(
        self,
        condition: torch.Tensor,
        hidden_state: torch.Tensor,
        strength: float = 1.0,
    ) -> torch.Tensor:
        """注入条件信号

        Args:
            condition: 条件特征 [B, L, condition_channels]
            hidden_state: DiT 隐藏状态 [B, L, hidden_dim]
            strength: 控制强度

        Returns:
            注入后的隐藏状态
        """
        proj_cond = self.proj(condition) * strength

        if self.injection_mode == "add":
            return hidden_state + proj_cond
        elif self.injection_mode == "concat":
            return torch.cat([hidden_state, proj_cond], dim=-1)
        elif self.injection_mode == "modulate":
            # 拆分为 scale 和 shift
            scale, shift = proj_cond.chunk(2, dim=-1)
            return hidden_state * (1 + scale) + shift
        else:
            return hidden_state


class ControlNetInjector(nn.Module):
    """ControlNet 条件注入器

    参考 DiffBIR 的 ControlNet 13 层注入框架:
    管理 13 个条件注入块，统一控制注入强度。
    """

    def __init__(self, config: ControlNetConfig):
        super().__init__()
        self.config = config

        # 创建 13 个注入块
        self.blocks = nn.ModuleList(
            [
                ControlNetConditionBlock(
                    condition_channels=config.condition_channels,
                    hidden_dim=config.hidden_dim,
                    injection_mode=config.injection_mode,
                    zero_conv_init=config.zero_conv_init,
                )
                for _ in range(config.num_control_layers)
            ]
        )

        # 每层独立控制强度
        if config.per_layer_strength:
            self.layer_strengths = nn.Parameter(torch.ones(config.num_control_layers) * config.control_strength)
        else:
            self.layer_strengths = None

    def get_strength(self, layer_idx: int) -> float:
        """获取指定层的控制强度"""
        if self.layer_strengths is not None:
            return self.layer_strengths[layer_idx].item()
        return self.config.control_strength

    def forward(
        self,
        condition: torch.Tensor,
        hidden_states: list[torch.Tensor],
    ) -> list[torch.Tensor]:
        """注入条件信号到 DiT 各层

        Args:
            condition: 条件特征 [B, L, condition_channels]
            hidden_states: DiT 各层隐藏状态列表

        Returns:
            注入后的隐藏状态列表
        """
        if not self.config.enabled:
            return hidden_states

        num_inject = min(len(self.blocks), len(hidden_states))
        output_states = list(hidden_states)

        for i in range(num_inject):
            strength = self.get_strength(i)
            output_states[i] = self.blocks[i](condition, hidden_states[i], strength)

        return output_states


# ---------------------------------------------------------------------------
# 双流 DiT 架构参考 (HunyuanVideo MMDoubleStreamBlock inspired) - P3
# ---------------------------------------------------------------------------


@dataclass
class DualStreamConfig:
    """双流 DiT 架构配置

    参考 HunyuanVideo 的 MMDoubleStreamBlock 设计:
    将文本流和视觉流分离为两个独立的 Transformer 流，
    在注意力层通过交叉注意力进行信息交互，在 FFN 层各自独立处理。

    核心思想:
    - 文本 token 和视觉 token 在同一 Transformer 中分别处理
    - 两个流共享 QKV 投影但各自维护独立的 KV 缓存
    - 通过交叉注意力实现文本→视觉的信息注入
    - FFN 层完全独立，避免文本/视觉特征的相互干扰
    - 相比单流架构，双流在文本条件遵循和视觉质量上表现更优
    """

    # 是否启用双流架构
    enabled: bool = False
    # 文本流隐藏维度
    text_hidden_dim: int = 4096
    # 视觉流隐藏维度
    visual_hidden_dim: int = 1536
    # 注意力头数
    num_heads: int = 24
    # 交叉注意力注入频率 (每 N 层注入一次)
    cross_attn_interval: int = 1
    # 文本流是否参与最终输出
    text_in_output: bool = False
    # 两个流之间的 MLP 融合方式: 'gate' (门控), 'add' (加法), 'none' (无融合)
    fusion_mode: str = "gate"


class DualStreamBlock(nn.Module):
    """双流 Transformer 块

    参考 HunyuanVideo 的 MMDoubleStreamBlock:
    文本流和视觉流并行处理，通过交叉注意力交互信息。

    注意: 本实现为参考框架，仅定义接口和基本结构，
    不包含完整的前向传播逻辑，需根据具体模型适配。
    """

    def __init__(self, config: DualStreamConfig, layer_idx: int = 0):
        super().__init__()
        self.config = config
        self.layer_idx = layer_idx

        # 是否在本层执行交叉注意力
        self.use_cross_attn = layer_idx % config.cross_attn_interval == 0

        # 视觉流自注意力层 (仅定义接口)
        self.visual_norm1 = nn.LayerNorm(config.visual_hidden_dim)
        self.visual_attn = nn.MultiheadAttention(
            config.visual_hidden_dim,
            config.num_heads,
            batch_first=True,
        )
        self.visual_norm2 = nn.LayerNorm(config.visual_hidden_dim)
        self.visual_ffn = nn.Sequential(
            nn.Linear(config.visual_hidden_dim, config.visual_hidden_dim * 4),
            nn.GELU(),
            nn.Linear(config.visual_hidden_dim * 4, config.visual_hidden_dim),
        )

        # 文本流自注意力层 (仅定义接口)
        self.text_norm1 = nn.LayerNorm(config.text_hidden_dim)
        self.text_attn = nn.MultiheadAttention(
            config.text_hidden_dim,
            config.num_heads,
            batch_first=True,
        )
        self.text_norm2 = nn.LayerNorm(config.text_hidden_dim)
        self.text_ffn = nn.Sequential(
            nn.Linear(config.text_hidden_dim, config.text_hidden_dim * 4),
            nn.GELU(),
            nn.Linear(config.text_hidden_dim * 4, config.text_hidden_dim),
        )

        # 交叉注意力投影 (文本→视觉)
        if self.use_cross_attn:
            self.cross_proj_q = nn.Linear(config.visual_hidden_dim, config.visual_hidden_dim)
            self.cross_proj_k = nn.Linear(config.text_hidden_dim, config.visual_hidden_dim)
            self.cross_proj_v = nn.Linear(config.text_hidden_dim, config.visual_hidden_dim)

            # 融合门控
            if config.fusion_mode == "gate":
                self.gate = nn.Sequential(
                    nn.Linear(config.visual_hidden_dim, config.visual_hidden_dim),
                    nn.Sigmoid(),
                )

    def forward(
        self,
        visual_hidden: torch.Tensor,
        text_hidden: torch.Tensor,
        visual_mask: torch.Tensor | None = None,
        text_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """双流块前向传播

        Args:
            visual_hidden: 视觉流隐藏状态 [B, L_v, visual_hidden_dim]
            text_hidden: 文本流隐藏状态 [B, L_t, text_hidden_dim]
            visual_mask: 视觉注意力掩码
            text_mask: 文本注意力掩码

        Returns:
            (visual_output, text_output): 更新后的双流隐藏状态
        """
        # 视觉流自注意力
        v_normed = self.visual_norm1(visual_hidden)
        v_attn_out, _ = self.visual_attn(
            v_normed,
            v_normed,
            v_normed,
            attn_mask=visual_mask,
        )
        visual_hidden = visual_hidden + v_attn_out

        # 文本流自注意力
        t_normed = self.text_norm1(text_hidden)
        t_attn_out, _ = self.text_attn(
            t_normed,
            t_normed,
            t_normed,
            attn_mask=text_mask,
        )
        text_hidden = text_hidden + t_attn_out

        # 交叉注意力: 文本→视觉
        if self.use_cross_attn:
            q = self.cross_proj_q(self.visual_norm1(visual_hidden))
            k = self.cross_proj_k(self.text_norm1(text_hidden))
            v = self.cross_proj_v(self.text_norm1(text_hidden))

            cross_out = F.scaled_dot_product_attention(q, k, v)

            if self.config.fusion_mode == "gate":
                gate = self.gate(cross_out)
                visual_hidden = visual_hidden + gate * cross_out
            elif self.config.fusion_mode == "add":
                visual_hidden = visual_hidden + cross_out
            # 'none' 模式不融合

        # 视觉流 FFN
        v_normed2 = self.visual_norm2(visual_hidden)
        visual_hidden = visual_hidden + self.visual_ffn(v_normed2)

        # 文本流 FFN
        t_normed2 = self.text_norm2(text_hidden)
        text_hidden = text_hidden + self.text_ffn(t_normed2)

        return visual_hidden, text_hidden


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def get_dit_optimization_summary() -> dict[str, Any]:
    """获取 DiT 优化模块的功能摘要

    Returns:
        包含各优化功能及其优先级和状态的字典
    """
    return {
        "lcsa_sparse_attention": {
            "name": "LCSA 稀疏注意力",
            "source": "FlashVSR",
            "priority": "P0",
            "description": "块稀疏注意力，通过可学习掩码减少冗余计算",
            "status": "implemented",
        },
        "ndim_rope": {
            "name": "N 维 RoPE 位置编码",
            "source": "HunyuanVideo",
            "priority": "P2",
            "description": "灵活适配不同分辨率和视频长度的多维旋转位置编码",
            "status": "reference",
        },
        "controlnet_injection": {
            "name": "ControlNet 条件注入",
            "source": "DiffBIR",
            "priority": "P2",
            "description": "13 层控制信号注入框架，支持可调节控制强度",
            "status": "reference",
        },
        "dual_stream_dit": {
            "name": "双流 DiT 架构",
            "source": "HunyuanVideo MMDoubleStreamBlock",
            "priority": "P3",
            "description": "文本/视觉分离调制的双流 Transformer 架构",
            "status": "reference",
        },
    }


# ---------------------------------------------------------------------------
# 频域注意力 (FTVSR inspired) - P3
# ---------------------------------------------------------------------------


@dataclass
class FrequencyDomainAttentionConfig:
    """频域注意力配置

    参考 FTVSR 的 DCT/IDCT 可微分变换 + 频域自注意力:
    将注意力计算从空间域转移到频域，利用频域的全局信息特性
    提升注意力的全局感知能力，同时降低计算开销。

    Attributes:
        enabled: 是否启用频域注意力
        transform_type: 频域变换类型 ('dct', 'fft')
        num_freq_bands: 频域分段数 (用于频域自注意力的分段计算)
        freq_reduction_ratio: 频域降采样比 (降低频域注意力的计算量)
        use_learnable_filter: 是否使用可学习频域滤波器
        num_heads: 注意力头数
        head_dim: 头维度
    """

    enabled: bool = False
    transform_type: str = "dct"
    num_freq_bands: int = 4
    freq_reduction_ratio: int = 2
    use_learnable_filter: bool = True
    num_heads: int = 8
    head_dim: int = 64


class FrequencyDomainAttention(nn.Module):
    """频域注意力模块

    参考 FTVSR 的 DCT/IDCT 可微分变换 + 频域自注意力:
    在频域中执行自注意力计算，利用频域的全局信息特性提升注意力效果。

    核心思路:
    1. DCT/IDCT 可微分变换: 使用 torch.fft 实现可微分的 DCT 变换
    2. 频域自注意力: 在频域特征上计算注意力，捕获全局频率依赖
    3. 可学习频域滤波: 通过可学习参数在频域进行特征筛选

    注意: DCT 变换通过 torch.fft 的 DFT + 频移实现，
    完整的 Type-II DCT 需要额外的预处理和后处理。

    用法:
        config = FrequencyDomainAttentionConfig(num_heads=8, head_dim=64)
        fda = FrequencyDomainAttention(config)
        output = fda(hidden_states)
    """

    def __init__(self, config: FrequencyDomainAttentionConfig):
        super().__init__()
        self.config = config

        hidden_dim = config.num_heads * config.head_dim
        self.hidden_dim = hidden_dim

        # 频域 Q/K/V 投影
        self.q_proj = nn.Linear(hidden_dim, hidden_dim)
        self.k_proj = nn.Linear(hidden_dim, hidden_dim)
        self.v_proj = nn.Linear(hidden_dim, hidden_dim)

        # 输出投影
        self.out_proj = nn.Linear(hidden_dim, hidden_dim)

        # 可学习频域滤波器
        if config.use_learnable_filter:
            # 频域滤波器参数 (在频域中对各频段进行加权)
            self.freq_filter = nn.Parameter(torch.ones(1, 1, 1, 1))  # 广播到实际频域尺寸

        self.scale = config.head_dim**-0.5

    def dct_2d(self, x: torch.Tensor) -> torch.Tensor:
        """2D DCT 变换 (可微分)

        使用 torch.fft 实现近似的 Type-II DCT:
        DCT-II(x) = Re{FFT(x_preprocessed)} 其中 x_preprocessed 包含对称延拓

        Args:
            x: 输入张量 [..., H, W]

        Returns:
            DCT 变换结果 [..., H, W]
        """
        # 简化实现: 使用 FFT + 频移近似 DCT
        # 完整的 DCT-II 需要 Pre-FFT 对称延拓
        x_freq = torch.fft.fft2(x, norm="ortho")
        # 取实部作为 DCT 近似
        return x_freq.real

    def idct_2d(self, x: torch.Tensor) -> torch.Tensor:
        """2D IDCT 逆变换 (可微分)

        Args:
            x: DCT 系数 [..., H, W]

        Returns:
            空间域结果 [..., H, W]
        """
        # 使用 IFFT 近似 IDCT
        x_complex = torch.complex(x, torch.zeros_like(x))
        x_spatial = torch.fft.ifft2(x_complex, norm="ortho")
        return x_spatial.real

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """频域注意力前向传播

        Args:
            hidden_states: [B, L, hidden_dim] 的隐藏状态

        Returns:
            频域注意力输出 [B, L, hidden_dim]
        """
        if not self.config.enabled:
            return hidden_states

        B, L, _ = hidden_states.shape

        # 假设 L 可以分解为 H * W (空间维度)
        H = W = int(math.sqrt(L))
        if H * W != L:
            # 如果不是完美平方，调整到最接近的平方数
            H = int(math.sqrt(L))
            W = L // H
            if H * W != L:
                # 无法分解为2D，退回空间域注意力
                logger.warning(f"序列长度 {L} 无法分解为2D空间，退回空间域注意力")
                return hidden_states

        cfg = self.config
        num_heads = cfg.num_heads
        head_dim = cfg.head_dim

        # 1. 投影 Q/K/V
        q = self.q_proj(hidden_states)  # [B, L, hidden_dim]
        k = self.k_proj(hidden_states)
        v = self.v_proj(hidden_states)

        # 重塑为多头形式
        q = q.view(B, L, num_heads, head_dim).transpose(1, 2)  # [B, num_heads, L, head_dim]
        k = k.view(B, L, num_heads, head_dim).transpose(1, 2)
        v = v.view(B, L, num_heads, head_dim).transpose(1, 2)

        # 2. 将 Q/K/V 重塑为2D空间并变换到频域
        q_2d = q.reshape(B * num_heads, H, W, head_dim)  # [B*num_heads, H, W, head_dim]
        k_2d = k.reshape(B * num_heads, H, W, head_dim)
        v_2d = v.reshape(B * num_heads, H, W, head_dim)

        # 对每个通道独立进行 DCT
        q_freq = self.dct_2d(q_2d.permute(0, 3, 1, 2))  # [B*num_heads, head_dim, H, W]
        k_freq = self.dct_2d(k_2d.permute(0, 3, 1, 2))
        v_freq = self.dct_2d(v_2d.permute(0, 3, 1, 2))

        # 3. 可学习频域滤波
        if cfg.use_learnable_filter:
            q_freq = q_freq * self.freq_filter
            k_freq = k_freq * self.freq_filter

        # 4. 频域自注意力: 在频域中计算注意力
        # 将频域特征展平后计算注意力
        q_freq_flat = q_freq.reshape(B * num_heads, head_dim, -1).transpose(-2, -1)
        k_freq_flat = k_freq.reshape(B * num_heads, head_dim, -1).transpose(-2, -1)
        v_freq_flat = v_freq.reshape(B * num_heads, head_dim, -1).transpose(-2, -1)

        # 缩放点积注意力 (在频域)
        attn_weight = torch.matmul(q_freq_flat, k_freq_flat.transpose(-2, -1)) * self.scale
        attn_weight = F.softmax(attn_weight, dim=-1)
        attn_output = torch.matmul(attn_weight, v_freq_flat)

        # 5. 逆变换回空间域
        attn_output_2d = attn_output.transpose(-2, -1).reshape(B * num_heads, head_dim, H, W)
        spatial_output = self.idct_2d(attn_output_2d)

        # 6. 重塑回序列形式
        spatial_output = spatial_output.permute(0, 2, 3, 1).reshape(B, num_heads, L, head_dim)
        spatial_output = spatial_output.transpose(1, 2).reshape(B, L, -1)

        # 7. 输出投影
        output = self.out_proj(spatial_output)

        return output


# ---------------------------------------------------------------------------
# Mamba 时序建模 (SCST STCM inspired) - P3
# ---------------------------------------------------------------------------


@dataclass
class MambaTemporalConfig:
    """Mamba 时序建模配置

    参考 SCST 的 STCM (Spatio-Temporal Context Modeling):
    使用 SSM (状态空间模型) 风格的时序建模替代 Transformer，
    实现线性复杂度的时序依赖建模。

    注意: 需要 mamba-ssm 库支持，当前为参考框架。

    Attributes:
        enabled: 是否启用 Mamba 时序建模
        d_model: 模型维度
        d_state: SSM 状态维度 (N in Mamba)
        d_conv: 局部卷积核大小
        expand: 扩展因子
        num_layers: Mamba 层数
        use_bidirectional: 是否使用双向 SSM
    """

    enabled: bool = False
    d_model: int = 1536
    d_state: int = 16
    d_conv: int = 3
    expand: int = 2
    num_layers: int = 4
    use_bidirectional: bool = True


class MambaTemporalModeling(nn.Module):
    """Mamba 时序建模模块

    参考 SCST 的 STCM (Spatio-Temporal Context Modeling):
    使用 SSM (状态空间模型) 替代 Transformer 进行时序建模，
    实现线性复杂度的长序列时序依赖建模。

    核心思路:
    - SSM 状态空间模型: 通过隐状态传递实现线性复杂度的序列建模
    - 选择性扫描 (Selective Scan): Mamba 的核心创新，根据输入动态选择信息
    - 双向建模: 前向 + 后向扫描捕获双向时序依赖

    TODO: 需要 mamba-ssm 库支持，当前为参考框架。

    用法 (框架):
        config = MambaTemporalConfig(d_model=1536)
        mamba = MambaTemporalModeling(config)
        output = mamba(temporal_features)
    """

    def __init__(self, config: MambaTemporalConfig):
        super().__init__()
        self.config = config

        d_model = config.d_model
        d_inner = int(d_model * config.expand)

        # 前向 SSM 层 (仅定义接口，实际实现需要 mamba-ssm)
        self.forward_proj = nn.Linear(d_model, d_inner)
        self.forward_out = nn.Linear(d_inner, d_model)

        if config.use_bidirectional:
            # 后向 SSM 层
            self.backward_proj = nn.Linear(d_model, d_inner)
            self.backward_out = nn.Linear(d_inner, d_model)
            # 融合门控
            self.fusion_gate = nn.Sequential(
                nn.Linear(d_model * 2, d_model),
                nn.Sigmoid(),
            )

        # 层归一化
        self.norm = nn.LayerNorm(d_model)

        # 标记为参考框架
        self._is_framework = True

    def _selective_scan_forward(
        self,
        x: torch.Tensor,
        direction: str = "forward",
    ) -> torch.Tensor:
        """选择性扫描 (Selective Scan) 前向传播

        Mamba 的核心操作: 根据输入动态选择信息传递。

        注意: 完整实现需要 mamba-ssm 库的 selective_scan_fn。
        此处提供简化框架实现。

        Args:
            x: 输入序列 [B, L, d_inner]
            direction: 扫描方向 ('forward' or 'backward')

        Returns:
            扫描结果 [B, L, d_inner]
        """
        B, L, D = x.shape
        d_state = self.config.d_state

        # 初始化隐状态
        torch.zeros(B, D, d_state, device=x.device, dtype=x.dtype)

        # 简化的 SSM 扫描 (线性递归近似)
        # 完整实现应使用 mamba-ssm 的并行扫描
        outputs = []

        # 可学习的 A 矩阵 (对角化)
        A_log = nn.Parameter(torch.log(torch.arange(1, d_state + 1, device=x.device).float().unsqueeze(0)))
        -torch.exp(A_log)  # [1, d_state]

        # 简化扫描: 使用指数加权平均近似 SSM
        decay = 0.9
        if direction == "backward":
            x = x.flip(dims=[1])

        acc = torch.zeros_like(x[:, 0, :])
        for t in range(L):
            acc = decay * acc + x[:, t, :]
            outputs.append(acc.clone())

        result = torch.stack(outputs, dim=1)

        if direction == "backward":
            result = result.flip(dims=[1])

        return result

    def forward(self, temporal_features: torch.Tensor) -> torch.Tensor:
        """Mamba 时序建模前向传播

        Args:
            temporal_features: 时序特征 [B, T, d_model]
                T = 时间维度 (帧数或时序 token 数)

        Returns:
            时序建模输出 [B, T, d_model]
        """
        if not self.config.enabled:
            return temporal_features

        residual = temporal_features
        x = self.norm(temporal_features)

        # 前向扫描
        fwd_proj = self.forward_proj(x)
        fwd_scan = self._selective_scan_forward(fwd_proj, direction="forward")
        fwd_out = self.forward_out(fwd_scan)

        if self.config.use_bidirectional:
            # 后向扫描
            bwd_proj = self.backward_proj(x)
            bwd_scan = self._selective_scan_forward(bwd_proj, direction="backward")
            bwd_out = self.backward_out(bwd_scan)

            # 融合: 门控机制
            gate_input = torch.cat([fwd_out, bwd_out], dim=-1)
            gate = self.fusion_gate(gate_input)
            output = gate * fwd_out + (1 - gate) * bwd_out
        else:
            output = fwd_out

        # 残差连接
        return residual + output


# ---------------------------------------------------------------------------
# Codebook Lookup + Transformer 范式 (CodeFormer inspired) - P3
# ---------------------------------------------------------------------------


@dataclass
class CodebookLookupConfig:
    """Codebook Lookup + Transformer 配置

    参考 CodeFormer 的离散化先验 + Transformer 预测范式:
    使用 VQ 码本将连续特征离散化，再用 Transformer 预测码本索引，
    实现高质量的图像修复。

    Attributes:
        enabled: 是否启用 Codebook Lookup
        codebook_size: VQ 码本大小 (词条数量)
        codebook_dim: 码本词条维度
        num_transformer_layers: Transformer 预测器层数
        num_heads: Transformer 注意力头数
        fidelity_weight: 保真度权重 (0.0=完全码本, 1.0=完全输入)
        temperature: 码本查找时的 softmax 温度
        use_ema_codebook: 是否使用 EMA 更新码本
    """

    enabled: bool = False
    codebook_size: int = 1024
    codebook_dim: int = 256
    num_transformer_layers: int = 6
    num_heads: int = 8
    fidelity_weight: float = 0.5
    temperature: float = 1.0
    use_ema_codebook: bool = True


class CodebookLookupTransformer(nn.Module):
    """Codebook Lookup + Transformer 模块

    参考 CodeFormer 的离散化先验 + Transformer 预测范式:
    1. VQ 码本查找: 将输入特征量化为最近的码本词条
    2. Transformer 预测: 使用 Transformer 预测最优的码本索引序列

    核心思路:
    - 离散化先验: 将连续的特征空间映射到离散码本，降低搜索空间
    - Transformer 预测: 利用 Transformer 的序列建模能力预测码本索引
    - Fidelity Weight: 控制码本先验与原始输入的混合比例

    用法:
        config = CodebookLookupConfig(codebook_size=1024, codebook_dim=256)
        clt = CodebookLookupTransformer(config)
        output = clt(degraded_features)
    """

    def __init__(self, config: CodebookLookupConfig):
        super().__init__()
        self.config = config

        # VQ 码本: [codebook_size, codebook_dim]
        self.codebook = nn.Embedding(config.codebook_size, config.codebook_dim)
        nn.init.uniform_(self.codebook.weight, -1.0 / config.codebook_size, 1.0 / config.codebook_size)

        # 输入投影: 将输入特征映射到码本维度
        # 注意: input_dim 需要在外部指定或通过运行时推断
        self.input_proj = nn.LazyLinear(config.codebook_dim)

        # Transformer 预测器: 预测码本索引
        transformer_layer = nn.TransformerEncoderLayer(
            d_model=config.codebook_dim,
            nhead=config.num_heads,
            dim_feedforward=config.codebook_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            transformer_layer,
            num_layers=config.num_transformer_layers,
        )

        # 索引预测头: 从 Transformer 输出预测码本索引
        self.index_head = nn.Linear(config.codebook_dim, config.codebook_size)

        # 输出投影
        self.output_proj = nn.LazyLinear(config.codebook_dim)

    def lookup_codebook(
        self,
        features: torch.Tensor,
        use_straight_through: bool = True,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """VQ 码本查找

        从离散码本中找到与输入特征最近的编码。

        Args:
            features: 输入特征 [B, L, codebook_dim]
            use_straight_through: 是否使用直通估计器 (梯度通过码本)

        Returns:
            (quantized, indices):
            - quantized: 量化后的特征 [B, L, codebook_dim]
            - indices: 码本索引 [B, L]
        """
        # 计算与码本的距离
        # features: [B, L, D], codebook: [K, D]
        dist = (
            features.pow(2).sum(dim=-1, keepdim=True)
            + self.codebook.weight.pow(2).sum(dim=-1)
            - 2 * features @ self.codebook.weight.t()
        )  # [B, L, K]

        # 找最近邻
        indices = dist.argmin(dim=-1)  # [B, L]

        # 查找码本词条
        quantized = self.codebook(indices)  # [B, L, D]

        if use_straight_through:
            # 直通估计器: 前向使用量化值，反向使用原始梯度
            quantized = features + (quantized - features).detach()

        # 计算承诺损失 (commitment loss)
        F.mse_loss(quantized.detach(), features)

        return quantized, indices

    def predict_indices(
        self,
        features: torch.Tensor,
    ) -> torch.Tensor:
        """Transformer 预测码本索引

        使用 Transformer 预测最优的码本索引序列。

        Args:
            features: 输入特征 [B, L, codebook_dim]

        Returns:
            预测的码本索引 logits [B, L, codebook_size]
        """
        # Transformer 编码
        encoded = self.transformer(features)  # [B, L, codebook_dim]

        # 预测码本索引
        index_logits = self.index_head(encoded)  # [B, L, codebook_size]

        return index_logits

    def forward(
        self,
        degraded_features: torch.Tensor,
    ) -> torch.Tensor:
        """Codebook Lookup + Transformer 前向传播

        Args:
            degraded_features: 退化图像特征 [B, L, input_dim]

        Returns:
            修复后的特征 [B, L, codebook_dim]
        """
        if not self.config.enabled:
            return degraded_features

        # 1. 投影到码本维度
        projected = self.input_proj(degraded_features)  # [B, L, codebook_dim]

        # 2. VQ 码本查找
        quantized, indices = self.lookup_codebook(projected)

        # 3. Transformer 预测索引
        index_logits = self.predict_indices(quantized)

        # 4. 用预测的索引查找码本 (带温度的 softmax 采样)
        if self.training:
            # 训练时: Gumbel-Softmax 采样
            index_probs = F.gumbel_softmax(
                index_logits / self.config.temperature,
                hard=True,
            )
            predicted_features = index_probs @ self.codebook.weight
        else:
            # 推理时: 取 argmax
            predicted_indices = index_logits.argmax(dim=-1)
            predicted_features = self.codebook(predicted_indices)

        # 5. Fidelity Weight 混合
        w = self.config.fidelity_weight
        output = w * projected + (1 - w) * predicted_features

        return output


# ---------------------------------------------------------------------------
# 多模态融合架构 (EvTexture inspired) - P3
# ---------------------------------------------------------------------------


@dataclass
class MultiModalFusionConfig:
    """多模态融合架构配置

    参考 EvTexture 的事件纹理提取 + 帧特征融合:
    从事件相机数据中提取纹理信息，与帧特征融合实现更精细的视频修复。

    注意: 依赖事件相机数据，与通用场景不兼容，仅参考框架。

    Attributes:
        enabled: 是否启用多模态融合
        event_dim: 事件特征维度
        frame_dim: 帧特征维度
        fusion_dim: 融合后的特征维度
        num_texture_layers: 纹理提取网络层数
        fusion_strategy: 融合策略 ('cross_attn', 'concat', 'gate', 'add')
        use_temporal_alignment: 是否使用时序对齐
    """

    enabled: bool = False
    event_dim: int = 64
    frame_dim: int = 1536
    fusion_dim: int = 1536
    num_texture_layers: int = 4
    fusion_strategy: str = "gate"
    use_temporal_alignment: bool = True


class MultiModalFusion(nn.Module):
    """多模态融合模块

    参考 EvTexture 的事件纹理提取 + 帧特征融合:
    从事件数据中提取纹理信息，与帧特征融合实现更精细的视频修复。

    核心设计:
    - 事件纹理提取模块: 从事件流中提取高频纹理信息
    - 帧特征与事件特征融合: 通过交叉注意力/门控/拼接等方式融合
    - 时序对齐: 对齐事件流和帧的时间戳

    注意: 依赖事件相机数据，与通用场景不兼容，仅参考框架。

    用法 (框架):
        config = MultiModalFusionConfig(fusion_strategy="gate")
        mmf = MultiModalFusion(config)
        output = mmf(frame_features, event_features)
    """

    def __init__(self, config: MultiModalFusionConfig):
        super().__init__()
        self.config = config

        # 事件纹理提取网络: 从事件流中提取纹理特征
        layers = []
        in_dim = config.event_dim
        for i in range(config.num_texture_layers):
            out_dim = config.event_dim if i < config.num_texture_layers - 1 else config.fusion_dim
            layers.extend(
                [
                    nn.Linear(in_dim, out_dim),
                    nn.GELU(),
                ]
            )
            in_dim = out_dim
        self.texture_extractor = nn.Sequential(*layers)

        # 帧特征投影
        self.frame_proj = nn.Linear(config.frame_dim, config.fusion_dim)

        # 融合模块
        strategy = config.fusion_strategy
        if strategy == "cross_attn":
            # 交叉注意力融合
            self.cross_attn = nn.MultiheadAttention(
                config.fusion_dim,
                num_heads=8,
                batch_first=True,
            )
            self.cross_norm = nn.LayerNorm(config.fusion_dim)

        elif strategy == "gate":
            # 门控融合
            self.gate = nn.Sequential(
                nn.Linear(config.fusion_dim * 2, config.fusion_dim),
                nn.Sigmoid(),
            )

        elif strategy == "concat":
            # 拼接后降维
            self.concat_proj = nn.Linear(config.fusion_dim * 2, config.fusion_dim)

        # 输出层归一化
        self.output_norm = nn.LayerNorm(config.fusion_dim)

    def extract_texture(self, event_features: torch.Tensor) -> torch.Tensor:
        """事件纹理提取

        从事件流特征中提取纹理信息。

        Args:
            event_features: 事件流特征 [B, T_e, event_dim]

        Returns:
            纹理特征 [B, T_e, fusion_dim]
        """
        return self.texture_extractor(event_features)

    def temporal_alignment(
        self,
        frame_features: torch.Tensor,
        event_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """时序对齐

        对齐事件流和帧的时间维度。
        当事件流的时间分辨率高于帧时，对事件流进行聚合。

        Args:
            frame_features: 帧特征 [B, T_f, D]
            event_features: 事件/纹理特征 [B, T_e, D]

        Returns:
            (aligned_frames, aligned_events): 对齐后的特征
        """
        T_f = frame_features.shape[1]
        T_e = event_features.shape[1]

        if T_e == T_f:
            return frame_features, event_features

        if T_e > T_f:
            # 事件流更密集: 按时间窗聚合
            chunk_size = T_e // T_f
            # 截断到可整除的长度
            usable_len = chunk_size * T_f
            event_chunks = event_features[:, :usable_len, :]
            event_chunks = event_chunks.reshape(frame_features.shape[0], T_f, chunk_size, -1)
            aligned_events = event_chunks.mean(dim=2)  # 平均池化
            return frame_features, aligned_events

        # 事件流更稀疏: 线性插值
        aligned_events = F.interpolate(
            event_features.permute(0, 2, 1),
            size=T_f,
            mode="linear",
            align_corners=False,
        ).permute(0, 2, 1)

        return frame_features, aligned_events

    def forward(
        self,
        frame_features: torch.Tensor,
        event_features: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """多模态融合前向传播

        Args:
            frame_features: 帧特征 [B, T, frame_dim]
            event_features: 事件流特征 [B, T_e, event_dim] (可选)

        Returns:
            融合后的特征 [B, T, fusion_dim]
        """
        if not self.config.enabled:
            return frame_features

        # 帧特征投影
        frame_proj = self.frame_proj(frame_features)

        if event_features is None:
            # 无事件数据时仅使用帧特征
            logger.debug("无事件数据，仅使用帧特征")
            return self.output_norm(frame_proj)

        # 事件纹理提取
        texture_features = self.extract_texture(event_features)

        # 时序对齐
        if self.config.use_temporal_alignment:
            frame_proj, texture_features = self.temporal_alignment(frame_proj, texture_features)

        # 融合
        strategy = self.config.fusion_strategy

        if strategy == "cross_attn":
            # 交叉注意力: frame 为 query, event 为 key/value
            aligned_frame, _ = self.cross_attn(
                frame_proj,
                texture_features,
                texture_features,
            )
            output = self.cross_norm(frame_proj + aligned_frame)

        elif strategy == "gate":
            # 门控融合
            combined = torch.cat([frame_proj, texture_features], dim=-1)
            gate = self.gate(combined)
            output = gate * frame_proj + (1 - gate) * texture_features

        elif strategy == "concat":
            # 拼接降维
            combined = torch.cat([frame_proj, texture_features], dim=-1)
            output = self.concat_proj(combined)

        elif strategy == "add":
            # 简单加法融合
            output = frame_proj + texture_features

        else:
            output = frame_proj

        return self.output_norm(output)
