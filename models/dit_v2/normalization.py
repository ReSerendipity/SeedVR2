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

"""归一化层工厂模块。

提供 ``get_norm_layer`` 工厂函数，根据类型名称返回归一化层构造器：

- ``None``: 恒等映射（不做归一化）。
- ``"layer"``: LayerNorm（层归一化）。
- ``"rms"``: RMSNorm（均方根归一化）。
- ``"fusedln"``: Apex FusedLayerNorm（融合加速，不可用时回退到 LayerNorm）。
- ``"fusedrms"``: Apex FusedRMSNorm（融合加速，不可用时回退到 RMSNorm）。

归一化算法:
    LayerNorm::

        y = (x - mean) / sqrt(var + eps) * gamma + beta

    RMSNorm::

        y = x / sqrt(mean(x^2) + eps) * gamma

    RMSNorm 省去了均值减法，计算量更小，效果与 LayerNorm 相当。
"""

from typing import Callable, Optional
import torch
from torch import nn

try:
    from apex.normalization import FusedLayerNorm as _ApexFusedLayerNorm
    from apex.normalization import FusedRMSNorm as _ApexFusedRMSNorm
    _apex_available = True
except ImportError:
    _apex_available = False

norm_layer_type = Callable[[int, float, bool], nn.Module]


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization。

    Args:
        dim: 归一化维度。
        eps: 数值稳定常数。
        elementwise_affine: 是否使用可学习缩放参数。
    """

    def __init__(self, dim: int, eps: float = 1e-6, elementwise_affine: bool = True):
        super().__init__()
        self.eps = eps
        if elementwise_affine:
            self.weight = nn.Parameter(torch.ones(dim))
        else:
            self.weight = None

    def _norm(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)

    def forward(self, x):
        """RMSNorm 前向传播。"""
        output = self._norm(x.float()).type_as(x)
        if self.weight is not None:
            output = output * self.weight
        return output


def get_norm_layer(norm_type: Optional[str]) -> norm_layer_type:
    """根据类型名称返回归一化层构造函数。

    返回的构造函数签名为 ``(dim, eps, elementwise_affine) -> nn.Module``。

    Args:
        norm_type: 归一化类型，支持 None、``"layer"``、``"rms"``、``"fusedln"``、``"fusedrms"``。

    Returns:
        norm_layer_type: 归一化层构造函数。
    """

    def _norm_layer(dim: int, eps: float, elementwise_affine: bool):
        if norm_type is None:
            return nn.Identity()
        if norm_type == "layer":
            return nn.LayerNorm(
                normalized_shape=dim, eps=eps, elementwise_affine=elementwise_affine
            )
        if norm_type == "rms":
            return RMSNorm(dim=dim, eps=eps, elementwise_affine=elementwise_affine)
        if norm_type == "fusedln":
            if _apex_available:
                return _ApexFusedLayerNorm(
                    normalized_shape=dim, eps=eps, elementwise_affine=elementwise_affine
                )
            else:
                import warnings
                warnings.warn("apex FusedLayerNorm not available, falling back to LayerNorm")
                return nn.LayerNorm(
                    normalized_shape=dim, eps=eps, elementwise_affine=elementwise_affine
                )
        if norm_type == "fusedrms":
            if _apex_available:
                return _ApexFusedRMSNorm(
                    normalized_shape=dim, eps=eps, elementwise_affine=elementwise_affine
                )
            else:
                import warnings
                warnings.warn("apex FusedRMSNorm not available, falling back to RMSNorm")
                return RMSNorm(dim=dim, eps=eps, elementwise_affine=elementwise_affine)
        raise NotImplementedError(f"{norm_type} is not supported")

    return _norm_layer
