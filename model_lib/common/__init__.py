"""model_lib.common — SeedVR2 模型共用工具包（本地最小实现）。

上游 ByteDance SeedVR2 的 ``common/`` 子包（context_parallel / fp8 / moe）未能随模型
源码一并 vendor 到本仓库（SOURCE.md 注明来源仓库可能为私有/归档）。本目录提供与
``model_lib/dit/nadit.py`` 导入 API 兼容的最小实现：

- 默认全部功能关闭：单卡、FP16、无 MoE，与项目当前配置（configs_3b/config.json 等
  未启用 fp8 / na_moe / context-parallel）保持一致，不改变现有推理行为。
- 若后续要启用 FP8 / MoE / 上下文并行，请在对应模块中实现真正的量化/并行逻辑。
"""

from .context_parallel import get_context_parallel_group, initialize_context_parallel
from .fp8 import FP8Linear, apply_fp8_linear_optimization, is_fp8_enabled
from .moe import build_moe_layer

__all__ = [
    "get_context_parallel_group",
    "initialize_context_parallel",
    "FP8Linear",
    "apply_fp8_linear_optimization",
    "is_fp8_enabled",
    "build_moe_layer",
]
