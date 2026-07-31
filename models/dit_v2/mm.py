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

"""多模态模块包装工具。

相比 v1 增加了 vid_only 模式支持，最后一层可仅处理视频分支。

- **MMArg**: 携带 vid/txt 值的数据类。
- **MMModule**: 多模态模块包装，支持共享权重、独立权重、vid_only 三种模式。
- **get_args/get_kwargs**: 从 MMArg 参数中提取指定分支的值。
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple
import torch
from torch import nn


@dataclass
class MMArg:
    """多模态参数容器，携带 vid 和 txt 两个分支的值。

    Attributes:
        vid: 视频分支值。
        txt: 文本分支值。
    """
    vid: Any
    txt: Any


def get_args(key: str, args: List[Any]) -> List[Any]:
    """从位置参数中提取指定分支的值。

    Args:
        key: 分支名 'vid' 或 'txt'。
        args: 原始参数列表。

    Returns:
        List[Any]: 提取后的参数。
    """
    return [getattr(v, key) if isinstance(v, MMArg) else v for v in args]


def get_kwargs(key: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """从关键字参数中提取指定分支的值。

    Args:
        key: 分支名。
        kwargs: 原始参数字典。

    Returns:
        Dict[str, Any]: 提取后的参数字典。
    """
    return {k: getattr(v, key) if isinstance(v, MMArg) else v for k, v in kwargs.items()}


class MMModule(nn.Module):
    """多模态模块包装器，支持共享/独立/vid-only 三种权重模式。

    Args:
        module: 要包装的模块类。
        *args: 构造参数。
        shared_weights: 是否 vid/txt 共享同一模块。
        vid_only: 是否仅处理视频分支（最后一层优化）。
        **kwargs: 构造关键字参数。
    """

    def __init__(
        self,
        module: Callable[..., nn.Module],
        *args,
        shared_weights: bool = False,
        vid_only: bool = False,
        **kwargs,
    ):
        super().__init__()
        self.shared_weights = shared_weights
        self.vid_only = vid_only
        if self.shared_weights:
            assert get_args("vid", args) == get_args("txt", args)
            assert get_kwargs("vid", kwargs) == get_kwargs("txt", kwargs)
            self.all = module(*get_args("vid", args), **get_kwargs("vid", kwargs))
        else:
            self.vid = module(*get_args("vid", args), **get_kwargs("vid", kwargs))
            self.txt = (
                module(*get_args("txt", args), **get_kwargs("txt", kwargs))
                if not vid_only
                else None
            )

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        *args,
        **kwargs,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，分别对 vid/txt 分支执行模块计算。

        Args:
            vid: 视频输入。
            txt: 文本输入。
            *args: 额外位置参数。
            **kwargs: 额外关键字参数。

        Returns:
            (vid_out, txt_out) 元组；vid_only 时 txt_out 保持不变。
        """
        vid_module = self.vid if not self.shared_weights else self.all
        vid = vid_module(vid, *get_args("vid", args), **get_kwargs("vid", kwargs))
        if not self.vid_only:
            txt_module = self.txt if not self.shared_weights else self.all
            txt = txt_module(txt, *get_args("txt", args), **get_kwargs("txt", kwargs))
        return vid, txt
