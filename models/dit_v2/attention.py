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

import torch
import torch.nn.functional as F

try:
    from flash_attn import flash_attn_varlen_func
    _flash_attn_available = True
except ImportError:
    _flash_attn_available = False

from torch import nn

class TorchAttention(nn.Module):
    def tflops(self, args, kwargs, output) -> float:
        assert len(args) == 0 or len(args) > 2, "query, key should both provided by args / kwargs"
        q = kwargs.get("query") or args[0]
        k = kwargs.get("key") or args[1]
        b, h, sq, d = q.shape
        b, h, sk, d = k.shape
        return b * h * (4 * d * (sq / 1e6) * (sk / 1e6))

    def forward(self, *args, **kwargs):
        return F.scaled_dot_product_attention(*args, **kwargs)


class FlashAttentionVarlen(nn.Module):
    def tflops(self, args, kwargs, output) -> float:
        cu_seqlens_q = kwargs["cu_seqlens_q"]
        cu_seqlens_k = kwargs["cu_seqlens_k"]
        _, h, d = output.shape
        seqlens_q = (cu_seqlens_q[1:] - cu_seqlens_q[:-1]) / 1e6
        seqlens_k = (cu_seqlens_k[1:] - cu_seqlens_k[:-1]) / 1e6
        return h * (4 * d * (seqlens_q * seqlens_k).sum())

    def forward(self, q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k, **kwargs):
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
    """Fallback implementation using torch SDPA when flash_attn is not available."""
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
        # flash_attn uses (seq, heads, dim), SDPA needs (batch, heads, seq, dim)
        q_i = q_i.transpose(1, 2)
        k_i = k_i.transpose(1, 2)
        v_i = v_i.transpose(1, 2)
        out_i = F.scaled_dot_product_attention(q_i, k_i, v_i)
        out_i = out_i.transpose(1, 2).squeeze(0)  # back to (seq, heads, dim)
        outputs.append(out_i)
    return torch.cat(outputs, dim=0)
