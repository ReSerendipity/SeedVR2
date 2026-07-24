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

"""视频帧张量重排布变换模块。

基于 einops.rearrange 封装的可调用变换类，用于视频帧维度重排。
"""

from einops import rearrange


class Rearrange:
    """基于 einops 模式字符串的可调用张量重排布变换。"""
    def __init__(self, pattern: str, **kwargs):
        self.pattern = pattern
        self.kwargs = kwargs

    def __call__(self, x):
        return rearrange(x, self.pattern, **self.kwargs)
