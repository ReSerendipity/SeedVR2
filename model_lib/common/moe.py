"""混合专家（MoE）层最小实现。

适配 ``model_lib/dit/nadit.py`` 的调用::

    build_moe_layer(config.na_moe, config.dim, config.mlp_expand_ratio)

项目当前配置（configs_3b/config.json 等）未声明 ``na_moe``，``build_moe_layer(None, ...)``
返回 None，模型不使用 MoE。若 config 非空，则构建一个简化 MoE（top-k 门控 + 专家 MLP），
接口与普通 MLP 一致（forward(x) -> x）。
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

__all__ = ["build_moe_layer"]


class _MoEMLP(nn.Module):
    """单专家 MLP：dim -> expand -> dim（SwiGLU 语义，对齐项目 MLP）。"""

    def __init__(self, dim: int, expand_ratio: int) -> None:
        super().__init__()
        hidden = int(dim * expand_ratio)
        self.w1 = nn.Linear(dim, hidden, bias=False)
        self.w2 = nn.Linear(hidden, dim, bias=False)
        self.w3 = nn.Linear(dim, hidden, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class _MoE(nn.Module):
    """简化 MoE：门控 top-k 路由到若干专家 MLP。"""

    def __init__(self, dim: int, expand_ratio: int, num_experts: int = 8, top_k: int = 2) -> None:
        super().__init__()
        self.num_experts = num_experts
        self.top_k = top_k
        self.gate = nn.Linear(dim, num_experts, bias=False)
        self.experts = nn.ModuleList([_MoEMLP(dim, expand_ratio) for _ in range(num_experts)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        logits = self.gate(x)
        k = min(self.top_k, self.num_experts)
        weights, indices = torch.topk(logits, k, dim=-1)
        weights = F.softmax(weights, dim=-1)
        out = torch.zeros_like(x)
        for j in range(k):
            idx = indices[..., j]
            w = weights[..., j].unsqueeze(-1)
            for e in range(self.num_experts):
                mask = idx == e
                if bool(mask.any()):
                    out[mask] = out[mask] + w[mask] * self.experts[e](x[mask])
        return out


def build_moe_layer(config, dim: int, expand_ratio: int):
    """构建 MoE 层。

    Args:
        config: ``na_moe`` 配置（含 num_experts / top_k / mlp_layers 等）；None 表示不启用 MoE。
        dim: 模型隐藏维度。
        expand_ratio: MLP 扩展倍数。

    Returns:
        ``nn.Module`` MoE 层；config 为空时返回 None。
    """
    if not config:
        return None
    num_experts = int(config.get("num_experts", 8))
    top_k = int(config.get("top_k", 2))
    return _MoE(dim, expand_ratio, num_experts=num_experts, top_k=top_k)
