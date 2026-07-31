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

"""NaDiT v2 Transformer Block 注册表。

提供 get_nablock 工厂函数，根据 block_type 字符串返回对应的 NaDiT v2 Transformer block 类。

已注册的 block 类型:
    - "mmdit_sr": NaMMSRTransformerBlock，多模态 Swin 风格变长窗口注意力 block，
      支持共享/独立权重、vid-only 最后层、多模态 RoPE。
"""

from .mmsr_block import NaMMSRTransformerBlock


nadit_blocks = {
    "mmdit_sr": NaMMSRTransformerBlock,
}


def get_nablock(block_type: str):
    """根据 block_type 名称返回 NaDiT v2 Transformer block 类。

    Args:
        block_type (str): Block 类型名称，目前支持 "mmdit_sr"。

    Returns:
        Type[nn.Module]: 对应的 Transformer block 类（未实例化）。

    Raises:
        NotImplementedError: 不支持的 block 类型。
    """
    if block_type in nadit_blocks:
        return nadit_blocks[block_type]
    raise NotImplementedError(f"{block_type} is not supported")
