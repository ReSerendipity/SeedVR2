# // Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# //
# // Licensed under the Apache License, Version 2.0 (the "License");
# // you may not use this file except in compliance with the License.
# // You may obtain a copy of the License at
# //
# //     http://www.apache.org/licenses/LICENSE-2.0
# //
# // Unless required by applicable law or agreed to in writing, software
# // distributed under the License is distributed on an "AS IS" BASIS,
# // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# // See the License for the specific language governing permissions and
# // limitations under the License.

"""注意力机制模块。

提供 DiT (Diffusion Transformer) 所需的注意力实现，包括：

- **TorchAttention**: 基于 PyTorch 原生 scaled_dot_product_attention (SDPA) 的标准注意力实现，
  作为 Flash Attention 不可用时的回退方案。
- **FlashAttentionVarlen**: 支持变长序列的 Flash Attention v2 实现，使用 `flash_attn_varlen_func`，
  当 flash_attn 库不可用时自动回退到 SDPA 逐段计算。

注意力机制算法:
    标准缩放点积注意力公式::

        Attention(Q, K, V) = softmax(Q * K^T / sqrt(d_k)) * V

    其中 Q (Query), K (Key), V (Value) 为输入投影后的张量，d_k 为每个注意力头的维度。
    缩放因子 1/sqrt(d_k) 用于防止点积值过大导致 softmax 梯度消失。

Flash Attention 优势:
    Flash Attention 通过 tiling 和重计算策略将注意力计算的内存复杂度从 O(N^2) 降低到 O(N)，
    显著提升长序列推理和训练效率。变长版本 (varlen) 通过 cu_seqlens 支持不同长度序列的批处理。
"""

import torch
import torch.nn.functional as F

try:
    from flash_attn import flash_attn_varlen_func
    _flash_attn_available = True
except ImportError:
    _flash_attn_available = False

from torch import nn


class TorchAttention(nn.Module):
    """基于 PyTorch 原生 SDPA 的注意力实现，作为 Flash Attention 不可用时的回退。

    使用 PyTorch 内置的 `torch.nn.functional.scaled_dot_product_attention`，
    该函数在 PyTorch 2.0+ 中自动选择最优的注意力后端（Flash Attention、Memory-Efficient Attention 或原生实现）。

    Attributes:
        无显式属性，但依赖 PyTorch 版本选择最佳实现路径。
    """

    def tflops(self, args, kwargs, output) -> float:
        """估算当前注意力计算的 TFLOPS (万亿次浮点运算每秒)。

        用于性能监控和基准测试，计算公式为::

            FLOPs = batch * heads * 4 * head_dim * seq_q * seq_k / 1e12

        Args:
            args: 位置参数，预期 query 在 args[0]，key 在 args[1]。
            kwargs: 关键字参数，可通过 'query' 和 'key' 获取张量。
            output: 注意力输出张量（未使用，保留接口兼容性）。

        Returns:
            float: 估算的 TFLOPS 值。
        """
        assert len(args) == 0 or len(args) > 2, "query, key should both provided by args / kwargs"
        q = kwargs.get("query") or args[0]
        k = kwargs.get("key") or args[1]
        b, h, sq, d = q.shape
        b, h, sk, d = k.shape
        return b * h * (4 * d * (sq / 1e6) * (sk / 1e6))

    def forward(self, *args, **kwargs):
        """执行缩放点积注意力计算。

        Args:
            *args: 传递给 F.scaled_dot_product_attention 的位置参数，通常为 (query, key, value)。
            **kwargs: 传递给 F.scaled_dot_product_attention 的关键字参数，如 attn_mask、dropout_p 等。

        Returns:
            torch.Tensor: 注意力输出张量，形状与 query 相同。
        """
        return F.scaled_dot_product_attention(*args, **kwargs)


class FlashAttentionVarlen(nn.Module):
    """支持变长序列的 Flash Attention 实现。

    使用 Flash Attention v2 的变长序列 API (`flash_attn_varlen_func`)，通过累积序列长度
    (cu_seqlens) 来处理批量中不同长度的序列，避免填充浪费。

    当 `flash_attn` 库不可用时，自动回退到 `_sdpa_varlen_fallback` 逐段使用 SDPA 计算。

    Note:
        输入张量形状为 (total_seq_len, num_heads, head_dim)，即所有序列拼接后的扁平化格式，
        而非标准的 (batch, heads, seq, dim) 格式。

    Attributes:
        无显式属性，但 _flash_attn_available 全局标志控制是否使用 flash_attn 库。
    """

    def tflops(self, args, kwargs, output) -> float:
        """估算变长注意力计算的 TFLOPS。

        通过 cu_seqlens 计算每个样本的实际序列长度，求和得到总 FLOPs。

        Args:
            args: 位置参数（未使用，长度从 kwargs 中获取）。
            kwargs: 关键字参数，必须包含 'cu_seqlens_q' 和 'cu_seqlens_k'。
            output: 注意力输出张量，形状为 (total_seq_len, num_heads, head_dim)。

        Returns:
            float: 估算的 TFLOPS 值。
        """
        cu_seqlens_q = kwargs["cu_seqlens_q"]
        cu_seqlens_k = kwargs["cu_seqlens_k"]
        _, h, d = output.shape
        seqlens_q = (cu_seqlens_q[1:] - cu_seqlens_q[:-1]) / 1e6
        seqlens_k = (cu_seqlens_k[1:] - cu_seqlens_k[:-1]) / 1e6
        return h * (4 * d * (seqlens_q * seqlens_k).sum())

    def forward(self, q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k, **kwargs):
        """执行变长序列 Flash Attention 计算。

        Args:
            q (torch.Tensor): Query 张量，形状 (total_q, num_heads, head_dim)。
            k (torch.Tensor): Key 张量，形状 (total_k, num_heads, head_dim)。
            v (torch.Tensor): Value 张量，形状 (total_k, num_heads, head_dim)。
            cu_seqlens_q (torch.Tensor): Query 的累积序列长度，形状 (batch + 1,)，
                dtype 为 torch.int32，首元素为 0。
            cu_seqlens_k (torch.Tensor): Key 的累积序列长度，形状 (batch + 1,)。
            max_seqlen_q (int): 批量中最长的 query 序列长度。
            max_seqlen_k (int): 批量中最长的 key 序列长度。
            **kwargs: 传递给 flash_attn_varlen_func 的额外参数，如 dropout_p、softmax_scale 等。
                自动设置 'deterministic' 参数以匹配 PyTorch 确定性算法设置。

        Returns:
            torch.Tensor: 注意力输出张量，形状 (total_q, num_heads, head_dim)。
        """
        if _flash_attn_available:
            kwargs["deterministic"] = torch.are_deterministic_algorithms_enabled()
            return flash_attn_varlen_func(
                q, k, v,
                cu_seqlens_q=cu_seqlens_q,
                cu_seqlens_k=cu_seqlens_k,
                max_seqlen_q=max_seqlen_q,
                max_seqlen_k=max_seqlen_k,
                **kwargs,
            )
        else:
            return _sdpa_varlen_fallback(
                q, k, v,
                cu_seqlens_q=cu_seqlens_q,
                cu_seqlens_k=cu_seqlens_k,
                max_seqlen_q=max_seqlen_q,
                max_seqlen_k=max_seqlen_k,
            )


def _sdpa_varlen_fallback(q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k):
    """Flash Attention 不可用时的 SDPA 回退实现。

    逐样本拆分变长序列，将每个样本的 (seq, heads, dim) 转换为 SDPA 所需的
    (1, heads, seq, dim) 格式，分别计算后再拼接回扁平化格式。

    Args:
        q (torch.Tensor): Query 张量，形状 (total_q, num_heads, head_dim)。
        k (torch.Tensor): Key 张量，形状 (total_k, num_heads, head_dim)。
        v (torch.Tensor): Value 张量，形状 (total_k, num_heads, head_dim)。
        cu_seqlens_q (torch.Tensor): Query 累积序列长度。
        cu_seqlens_k (torch.Tensor): Key 累积序列长度。
        max_seqlen_q (int): 最长 query 长度（未使用，保留接口）。
        max_seqlen_k (int): 最长 key 长度（未使用，保留接口）。

    Returns:
        torch.Tensor: 拼接后的注意力输出，形状 (total_q, num_heads, head_dim)。
    """
    batch_size = len(cu_seqlens_q) - 1
    outputs = []
    for i in range(batch_size):
        start_q = cu_seqlens_q[i].item()
        end_q = cu_seqlens_q[i + 1].item()
        start_k = cu_seqlens_k[i].item()
        end_k = cu_seqlens_k[i + 1].item()
        q_i = q[start_q:end_q].unsqueeze(0)  # (1, seq_q, heads, dim) -> need (1, heads, seq_q, dim)
        k_i = k[start_k:end_k].unsqueeze(0)
        v_i = v[start_k:end_k].unsqueeze(0)
        # flash_attn uses (seq, heads, dim), SDPA needs (batch, heads, seq, dim)
        q_i = q_i.transpose(1, 2)
        k_i = k_i.transpose(1, 2)
        v_i = v_i.transpose(1, 2)
        out_i = F.scaled_dot_product_attention(q_i, k_i, v_i)
        out_i = out_i.transpose(1, 2).squeeze(0)  # back to (seq, heads, dim)
        outputs.append(out_i)
    return torch.cat(outputs, dim=0)
