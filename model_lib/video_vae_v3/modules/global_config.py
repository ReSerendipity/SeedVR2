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

"""Video VAE 全局配置模块。

管理归一化层的内存分片阈值等全局运行时参数。当 GroupNorm 处理的张量
超过设定的内存上限时，会自动按通道分组进行分片计算以避免 OOM。
"""

_NORM_LIMIT = float("inf")
"""归一化层单张量内存上限（GiB），默认无限制。"""


def get_norm_limit() -> float:
    """获取归一化层的内存分片阈值。

    当待归一化的 5D 张量在展平为 (B*T, C, H, W) 后占用的显存超过该值时，
    GroupNorm 将按通道维度分块计算以降低峰值显存。

    Returns:
        float: 内存限制值，单位 GiB。float('inf') 表示不分片。
    """
    return _NORM_LIMIT


def set_norm_limit(value: float | None = None):
    """设置归一化层的内存分片阈值。

    Args:
        value: 新的内存限制值（GiB）。若为 None，则重置为无限制（inf）。

    Example:
        >>> set_norm_limit(2.0)  # 限制单张量归一化不超过2GB显存
        >>> set_norm_limit(None)  # 取消限制
    """
    global _NORM_LIMIT
    if value is None:
        value = float("inf")
    _NORM_LIMIT = value
