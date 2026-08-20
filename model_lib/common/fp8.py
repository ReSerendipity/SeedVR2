"""FP8 量化最小实现（默认关闭）。

适配 ``model_lib/dit/nadit.py`` 的调用::

    FP8Linear(in_features, out_features, bias=bias)
    is_fp8_enabled()
    apply_fp8_linear_optimization(model)

项目当前配置（configs_3b/config.json 等）未启用 fp8，``is_fp8_enabled()`` 默认返回
False，此时 ``FP8Linear`` 与 ``nn.Linear`` 行为完全一致，``apply_fp8_linear_optimization``
为空操作。可通过环境变量 ``SEEDVR2_FP8_ENABLED=1`` 显式开启；开启后 ``FP8Linear`` 仍
退化为普通线性层（未实现真正的 float8 内核）。
"""

from __future__ import annotations

import os

import torch.nn as nn

__all__ = ["FP8Linear", "apply_fp8_linear_optimization", "is_fp8_enabled"]


def is_fp8_enabled() -> bool:
    """是否启用 FP8。

    Returns:
        默认关闭（False）；可通过环境变量 ``SEEDVR2_FP8_ENABLED=1`` 显式开启。
    """
    return os.environ.get("SEEDVR2_FP8_ENABLED", "0") in ("1", "true", "True", "TRUE")


class FP8Linear(nn.Linear):
    """FP8 线性层（当前实现与 ``nn.Linear`` 等价，未做实际 FP8 量化）。"""

    def __init__(self, in_features: int, out_features: int, bias: bool = True) -> None:
        super().__init__(in_features, out_features, bias=bias)


def apply_fp8_linear_optimization(model: nn.Module) -> None:
    """将模型中的线性层替换为 FP8 版本。

    当前为空操作：不启用实际 FP8 量化，保持模型结构不变。
    """
    return None
