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

"""NaDiT v2 Patch 层工厂模块。

提供 get_na_patch_layers 工厂函数，根据 patch_type 字符串返回对应的
Patch 嵌入层 (NaPatchIn) 和 Patch 还原层 (NaPatchOut) 类。

Patch 层负责将视频的 3D 网格特征转换为 Transformer 所需的一维 token 序列，
以及将 Transformer 输出的 token 序列还原回 3D 网格特征。
"""


def get_na_patch_layers(patch_type="v1"):
    """根据 patch_type 返回 NaPatchIn 和 NaPatchOut 类。

    Args:
        patch_type (str): Patch 实现版本，目前仅支持 "v1"。

    Returns:
        Tuple[Type[nn.Module], Type[nn.Module]]: (NaPatchIn, NaPatchOut) 类元组。

    Raises:
        AssertionError: 不支持的 patch_type。
    """
    assert patch_type in ["v1"]
    if patch_type == "v1":
        from .patch_v1 import NaPatchIn, NaPatchOut
    return NaPatchIn, NaPatchOut
