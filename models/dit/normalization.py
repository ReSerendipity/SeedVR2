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

提供 get_norm_layer 函数，根据类型名称创建对应的归一化层，
支持 LayerNorm / RMSNorm / Apex 融合变体。
"""

from typing import Callable, Optional
from diffusers.models.normalization import RMSNorm
from torch import nn

# (dim: int, eps: float, elementwise_affine: bool)
norm_layer_type = Callable[[int, float, bool], nn.Module]

# Check apex availability
try:
    from apex.normalization import FusedLayerNorm as _ApexFusedLayerNorm
    from apex.normalization import FusedRMSNorm as _ApexFusedRMSNorm
    _apex_available = True
except ImportError:
    _apex_available = False


def get_norm_layer(norm_type: Optional[str]) -> norm_layer_type:
    """根据类型名称返回归一化层构造函数。

    支持: None(Identity), 'layer', 'rms', 'fusedln', 'fusedrms'。
    """

    def _norm_layer(dim: int, eps: float, elementwise_affine: bool):
        if norm_type is None:
            return nn.Identity()

        if norm_type == "layer":
            return nn.LayerNorm(
                normalized_shape=dim,
                eps=eps,
                elementwise_affine=elementwise_affine,
            )

        if norm_type == "rms":
            return RMSNorm(
                dim=dim,
                eps=eps,
                elementwise_affine=elementwise_affine,
            )

        if norm_type == "fusedln":
            if _apex_available:
                return _ApexFusedLayerNorm(
                    normalized_shape=dim,
                    elementwise_affine=elementwise_affine,
                    eps=eps,
                )
            else:
                import warnings
                warnings.warn("apex FusedLayerNorm not available, falling back to nn.LayerNorm")
                return nn.LayerNorm(
                    normalized_shape=dim,
                    eps=eps,
                    elementwise_affine=elementwise_affine,
                )

        if norm_type == "fusedrms":
            if _apex_available:
                return _ApexFusedRMSNorm(
                    normalized_shape=dim,
                    elementwise_affine=elementwise_affine,
                    eps=eps,
                )
            else:
                import warnings
                warnings.warn("apex FusedRMSNorm not available, falling back to RMSNorm")
                return RMSNorm(
                    dim=dim,
                    eps=eps,
                    elementwise_affine=elementwise_affine,
                )

        raise NotImplementedError(f"{norm_type} is not supported")

    return _norm_layer
