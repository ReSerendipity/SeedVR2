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

"""多模态 (Multi-Modal) 模块包装工具。

提供视频(vid)/文本(txt)双分支统一处理的工具类和函数：

- **MMArg**: 数据类，携带 vid 和 txt 两个分支的值，用于参数传递。
- **MMModule**: 多模态模块包装器，支持共享权重和独立权重两种模式，
  自动将参数分发到视频和文本分支并分别调用。
- **get_args/get_kwargs**: 从 MMArg 参数中提取指定分支的参数。

设计目的:
    在多模态 DiT (MM-DiT) 中，视频和文本通常经过相似但独立的投影层，
    MMModule 通过统一接口简化双分支代码，同时支持共享权重（视频文本共用同一层）
    和独立权重（视频文本各有独立层）两种配置。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn


@dataclass
class MMArg:
    """多模态参数容器，携带 vid 和 txt 两个分支的值。

    Attributes:
        vid (Any): 视频分支的值。
        txt (Any): 文本分支的值。
    """

    vid: Any
    txt: Any


def get_args(key: str, args: list[Any]) -> list[Any]:
    """从位置参数列表中提取指定分支的参数。

    遍历 args 列表，若元素是 MMArg 则提取其 key 属性（vid/txt），否则保持原样。

    Args:
        key (str): 要提取的分支名，'vid' 或 'txt'。
        args (List[Any]): 原始位置参数列表，可能包含 MMArg。

    Returns:
        List[Any]: 提取后的参数列表，MMArg 被替换为对应分支的值。
    """
    return [getattr(v, key) if isinstance(v, MMArg) else v for v in args]


def get_kwargs(key: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """从关键字参数字典中提取指定分支的参数。

    Args:
        key (str): 要提取的分支名，'vid' 或 'txt'。
        kwargs (Dict[str, Any]): 原始关键字参数字典，可能包含 MMArg。

    Returns:
        Dict[str, Any]: 提取后的参数字典，MMArg 被替换为对应分支的值。
    """
    return {k: getattr(v, key) if isinstance(v, MMArg) else v for k, v in kwargs.items()}


class MMModule(nn.Module):
    """多模态模块包装器，为视频和文本分支提供独立或共享的子模块。

    Args:
        module (Callable[..., nn.Module]): 要实例化的模块类（未初始化）。
        *args: 传递给模块构造函数的位置参数，MMArg 会被拆分。
        shared_weights (bool): 是否共享权重，若为 True 则 vid/txt 使用同一模块实例。
        **kwargs: 传递给模块构造函数的关键字参数，MMArg 会被拆分。

    Attributes:
        shared_weights (bool): 是否共享权重标志。
        all (nn.Module): 共享权重时的模块实例，仅当 shared_weights=True 时存在。
        vid (nn.Module): 视频分支模块，仅当 shared_weights=False 时存在。
        txt (nn.Module): 文本分支模块，仅当 shared_weights=False 时存在。
    """

    def __init__(
        self,
        module: Callable[..., nn.Module],
        *args,
        shared_weights: bool = False,
        **kwargs,
    ):
        super().__init__()
        self.shared_weights = shared_weights
        if self.shared_weights:
            assert get_args("vid", args) == get_args("txt", args)
            assert get_kwargs("vid", kwargs) == get_kwargs("txt", kwargs)
            self.all = module(*get_args("vid", args), **get_kwargs("vid", kwargs))
        else:
            self.vid = module(*get_args("vid", args), **get_kwargs("vid", kwargs))
            self.txt = module(*get_args("txt", args), **get_kwargs("txt", kwargs))

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        *args,
        **kwargs,
    ) -> tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，分别对视频和文本分支执行模块计算。

        Args:
            vid (torch.FloatTensor): 视频输入张量。
            txt (torch.FloatTensor): 文本输入张量。
            *args: 传递给子模块的位置参数。
            **kwargs: 传递给子模块的关键字参数。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor]: (vid_output, txt_output) 元组。
        """
        vid_module = self.vid if not self.shared_weights else self.all
        txt_module = self.txt if not self.shared_weights else self.all
        vid = vid_module(vid, *get_args("vid", args), **get_kwargs("vid", kwargs))
        txt = txt_module(txt, *get_args("txt", args), **get_kwargs("txt", kwargs))
        return vid, txt
