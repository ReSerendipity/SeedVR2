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

"""NaDiT v2 注意力模块注册表。

提供 get_attn 工厂函数，根据 attn_type 字符串返回对应的注意力实现类。

已注册的注意力类型:
    - "mm_full": NaMMAttention，多模态全局注意力（使用 Flash Attention v2 变长 API）。
"""

from .mmattn import NaMMAttention

attns = {
    "mm_full": NaMMAttention,
}


def get_attn(attn_type: str):
    """根据 attn_type 名称返回对应的注意力实现类。

    Args:
        attn_type (str): 注意力类型名称，目前支持 "mm_full"。

    Returns:
        Type[nn.Module]: 对应的注意力类（未实例化）。

    Raises:
        NotImplementedError: 不支持的注意力类型。
    """
    if attn_type in attns:
        return attns[attn_type]
    raise NotImplementedError(f"{attn_type} is not supported")
