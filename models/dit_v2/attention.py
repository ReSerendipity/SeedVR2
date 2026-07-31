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

提供两种注意力实现：

- **TorchAttention**: 基于 PyTorch 原生 ``scaled_dot_product_attention`` 的标准注意力，
  支持 Flash Attention、Memory-Efficient Attention 和 Math Attention 三种内核自动选择。
- **FlashAttentionVarlen**: 基于 flash-attn 库的变长序列 Flash Attention v2，
  使用 ``cu_seqlens`` 累积长度索引批量处理不同长度的序列，无需 padding。

注意力 FLOPs 估算:
    提供 ``tflops`` 方法估算注意力计算的理论 FLOPs（单位: TFLOPs），
    标准注意力 FLOPs = 4 * head_dim * sq * sk * num_heads / 1e12，
    变长版本对每个样本的 (q_len, k_len) 分别计算后求和。

回退机制:
    当 flash_attn 库不可用时，FlashAttentionVarlen 自动回退到
    ``_sdpa_varlen_fallback``：按 cu_seqlens 逐段拆分序列，
    分别调用 ``F.scaled_dot_product_attention`` 计算后拼接。
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
    """基于 PyTorch ``F.scaled_dot_product_attention`` 的标准注意力实现。

    自动利用 PyTorch 的 SDPA 优化后端（Flash Attention、Memory-Efficient 等），
    适用于固定形状张量的注意力计算。
    """

    def tflops(self, args, kwargs, output) -> float:
        """估算注意力计算的理论 TFLOPs。

        Args:
            args: 位置参数。
            kwargs: 关键字参数。
            output: 注意力输出张量。

        Returns:
            float: 理论 TFLOPs 值。
        """
        assert len(args) == 0 or len(args) > 2, "query, key should both provided by args / kwargs"
        q = kwargs.get("query") or args[0]
        k = kwargs.get("key") or args[1]
        b, h, sq, d = q.shape
        b, h, sk, d = k.shape
        return b * h * (4 * d * (sq / 1e6) * (sk / 1e6))

    def forward(self, *args, **kwargs):
        """前向传播，调用 ``F.scaled_dot_product_attention``。

        Args:
            *args: 传递给 SDPA 的位置参数 (q, k, v, attn_mask, ...)。
            **kwargs: 传递给 SDPA 的关键字参数。

        Returns:
            torch.Tensor: 注意力输出张量。
        """
        return F.scaled_dot_product_attention(*args, **kwargs)


class FlashAttentionVarlen(nn.Module):
    """支持变长序列的 Flash Attention v2 实现。

    使用 flash_attn 库的 ``flash_attn_varlen_func`` API，通过累积序列长度
    (cu_seqlens_q/cu_seqlens_k) 批量处理不同长度的序列。flash_attn 不可用时回退到 SDPA。

    输入形状约定:
        q/k/v 为 (total_len, num_heads, head_dim) 的扁平 3D 张量，
        cu_seqlens 为 (batch_size + 1,) 的 int32 累积索引，
        例如 batch_size=2, seq_lens=[3,5] 时 cu_seqlens=[0,3,8]。
    """

    def tflops(self, args, kwargs, output) -> float:
        """估算变长注意力的理论 TFLOPs。

        Args:
            args: 位置参数。
            kwargs: 关键字参数（需包含 cu_seqlens_q/cu_seqlens_k）。
            output: 注意力输出张量。

        Returns:
            float: 理论 TFLOPs 值。
        """
        cu_seqlens_q = kwargs["cu_seqlens_q"]
        cu_seqlens_k = kwargs["cu_seqlens_k"]
        _, h, d = output.shape
        seqlens_q = (cu_seqlens_q[1:] - cu_seqlens_q[:-1]) / 1e6
        seqlens_k = (cu_seqlens_k[1:] - cu_seqlens_k[:-1]) / 1e6
        return h * (4 * d * (seqlens_q * seqlens_k).sum())

    def forward(self, q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k, **kwargs):
        """前向传播，执行变长 Flash Attention。

        Args:
            q (torch.Tensor): 查询张量，形状 (total_q, num_heads, head_dim)。
            k (torch.Tensor): 键张量，形状 (total_k, num_heads, head_dim)。
            v (torch.Tensor): 值张量，形状 (total_k, num_heads, head_dim)。
            cu_seqlens_q (torch.Tensor): Q 的累积序列长度，形状 (b+1,)，int32。
            cu_seqlens_k (torch.Tensor): K/V 的累积序列长度，形状 (b+1,)，int32。
            max_seqlen_q (int): batch 中最长的 Q 序列长度。
            max_seqlen_k (int): batch 中最长的 K/V 序列长度。
            **kwargs: 传递给 flash_attn_varlen_func 的额外参数（dropout_p, softmax_scale 等）。

        Returns:
            torch.Tensor: 注意力输出，形状 (total_q, num_heads, head_dim)。
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
    """Flash Attention 不可用时的 SDPA 回退实现，逐段计算注意力后拼接。

    Args:
        q/k/v: 见 FlashAttentionVarlen.forward。
        cu_seqlens_q/cu_seqlens_k: 见 FlashAttentionVarlen.forward。
        max_seqlen_q/max_seqlen_k: 见 FlashAttentionVarlen.forward。

    Returns:
        torch.Tensor: 拼接后的注意力输出。
    """
    batch_size = len(cu_seqlens_q) - 1
    outputs = []
    for i in range(batch_size):
        start_q = cu_seqlens_q[i].item()
        end_q = cu_seqlens_q[i + 1].item()
        start_k = cu_seqlens_k[i].item()
        end_k = cu_seqlens_k[i + 1].item()
        q_i = q[start_q:end_q].unsqueeze(0)
        k_i = k[start_k:end_k].unsqueeze(0)
        v_i = v[start_k:end_k].unsqueeze(0)
        q_i = q_i.transpose(1, 2)
        k_i = k_i.transpose(1, 2)
        v_i = v_i.transpose(1, 2)
        out_i = F.scaled_dot_product_attention(q_i, k_i, v_i)
        out_i = out_i.transpose(1, 2).squeeze(0)
        outputs.append(out_i)
    return torch.cat(outputs, dim=0)
