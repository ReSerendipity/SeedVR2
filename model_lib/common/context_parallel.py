"""上下文并行（Context Parallel）最小实现。

适配 ``model_lib/dit/nadit.py`` 的调用::

    initialize_context_parallel(get_context_parallel_group(), 2, False)

本项目当前为单卡/单进程推理，上下文并行默认关闭（enable=False），因此本实现为
安全空操作：``get_context_parallel_group()`` 返回 None，``initialize_context_parallel``
在 enable=False 或 cp_size<=1 时不创建任何进程组。如需启用，请在 torch.distributed
初始化后按 world_size 切分 CP 组。
"""

from __future__ import annotations

__all__ = ["get_context_parallel_group", "initialize_context_parallel"]

# 全局上下文并行进程组（单进程下恒为 None）
_CP_GROUP = None


def get_context_parallel_group():
    """返回当前上下文并行的 torch.distributed 进程组。

    Returns:
        已初始化的 CP 进程组；未初始化/单进程时返回 None。
    """
    return _CP_GROUP


def initialize_context_parallel(group=None, cp_size: int = 1, enable: bool = False) -> None:
    """初始化上下文并行。

    Args:
        group: 外层进程组（单进程传 None）。
        cp_size: 上下文并行组大小。
        enable: 是否启用上下文并行。
    """
    global _CP_GROUP
    if not enable or cp_size <= 1:
        _CP_GROUP = None
        return
    # 多进程/多卡 CP 尚未实现；启用时在此按 world_size 切分进程组并赋值 _CP_GROUP。
    _CP_GROUP = group
