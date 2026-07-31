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

"""NaDiT Transformer Block 注册表。

提供 get_nablock 工厂函数，根据 block_type 字符串返回对应的 NaDiT Transformer block 类。

已注册的 block 类型:
    - "mmsr" (即 "mmdit_sr"): NaMMSRTransformerBlock，多模态 Swin 风格变长窗口注意力 block。
"""

from .mmsr_block import NaMMSRTransformerBlock

nadit_blocks = {
    "mmsr": NaMMSRTransformerBlock,
    "mmdit_sr": NaMMSRTransformerBlock,
}


def get_na_block(block_type: str):
    """根据 block_type 名称返回 NaDiT Transformer block 类。

    Args:
        block_type (str): Block 类型名称，如 "mmsr" 或 "mmdit_sr"。

    Returns:
        Type[nn.Module]: 对应的 Transformer block 类（未实例化）。

    Raises:
        NotImplementedError: 不支持的 block 类型。
    """
    if block_type in nadit_blocks:
        return nadit_blocks[block_type]
    raise NotImplementedError(f"{block_type} is not supported")
