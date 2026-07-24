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

"""多模态(Multi-Modal)模块包装工具。

提供 MMArg 数据类和 MMModule 包装器，用于统一处理视频/文本双分支
参数传递，支持共享权重和独立权重两种模式。
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple
import torch
from torch import nn


@dataclass
class MMArg:
    """多模态参数容器，携带 vid 和 txt 两个分支的值。"""
    vid: Any
    txt: Any


def get_args(key: str, args: List[Any]) -> List[Any]:
    return [getattr(v, key) if isinstance(v, MMArg) else v for v in args]


def get_kwargs(key: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: getattr(v, key) if isinstance(v, MMArg) else v for k, v in kwargs.items()}


class MMModule(nn.Module):
    """多模态模块包装器，为视频和文本分支提供独立或共享的子模块。"""
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
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        vid_module = self.vid if not self.shared_weights else self.all
        txt_module = self.txt if not self.shared_weights else self.all
        vid = vid_module(vid, *get_args("vid", args), **get_kwargs("vid", kwargs))
        txt = txt_module(txt, *get_args("txt", args), **get_kwargs("txt", kwargs))
        return vid, txt
