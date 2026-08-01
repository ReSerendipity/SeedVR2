"""Generate the new seedvr2_engine.py from the original file.

Keeps only the core methods (init, load, unload, destroy, query, config,
model loading) and imports pipeline mixins.
"""

from pathlib import Path

ENGINE_FILE = Path("bin/integrated_app/engines/seedvr2_engine.py")
ENGINES_DIR = ENGINE_FILE.parent

with open(ENGINE_FILE, encoding="utf-8") as f:
    lines = f.readlines()

# Core method line ranges (1-indexed, inclusive)
CORE_METHODS = [
    (602, 634),    # __init__
    (635, 648),    # set_progress_callback
    (649, 658),    # request_cancel
    (659, 677),    # _check_cancelled
    (678, 682),    # _reset_cancel_token
    (683, 703),    # _cleanup_after_error
    (704, 788),    # load_model
    (789, 844),    # _destroy_module
    (845, 850),    # _destroy_dit
    (851, 856),    # _destroy_vae
    (857, 891),    # unload_model
    (892, 958),    # _get_inference_config
    # Skip 959-1939 (video + image pipeline methods -> mixins)
    (1940, 1950),  # is_loaded
    (1951, 1973),  # get_model_info
    (1974, 2004),  # estimate_vram_required
    (2005, 2025),  # _resolve_device
    (2026, 2301),  # _load_dit_model
    (2302, 2459),  # _load_vae_model
    (2460, 2489),  # _load_vae_yaml_config
    (2490, 2529),  # _configure_diffusion (includes @torch.no_grad() at 2529? No, 2529 is the decorator for _vae_encode)
]

# Wait, line 2490 is _configure_diffusion and it ends before line 2529 which is @torch.no_grad()
# Let me check: line 2529 is the @torch.no_grad() decorator for _vae_encode (line 2530)
# So _configure_diffusion ends at line 2528
CORE_METHODS[-1] = (2490, 2528)  # _configure_diffusion: 2490-2528

# Build the new file
HEADER = '''"""SeedVR2 - SeedVR2 视频/图像修复推理引擎核心实现

本模块是 SeedVR2 推理引擎的主入口，定义了 SeedVR2Engine 类的核心骨架
（初始化、模型加载/卸载、配置管理、状态查询），以及推理管线的 mixin 组合。

结构重构后的模块布局（阶段二A）:
- ``_memory_utils.py``: 内存监控函数、数据变换类、常量、ImageInferenceConfig
- ``_vae_pipeline.py``: VAE 编解码管线 mixin（_VAEPipelineMixin）
- ``_dit_pipeline.py``: DiT 采样管线 mixin（_DitPipelineMixin）
- ``_video_pipeline.py``: 视频推理管线 mixin（_VideoPipelineMixin）
- ``_image_pipeline.py``: 图像推理管线 mixin（_ImagePipelineMixin）
- ``seedvr2_engine.py``: 本文件，组合所有 mixin 的主引擎类

推理流水线 (4 阶段):
1. VAE 编码: 像素空间 -> 潜空间 (VAE在GPU, DiT未加载)
2. DiT 采样: 低分辨率潜空间 -> 高分辨率潜空间 (DiT在GPU/BlockSwap, VAE在CPU)
3. VAE 解码: 潜空间 -> 像素空间 (VAE在GPU, DiT已销毁)
4. 后处理: 颜色校正、小波重建、锐化、EXIF复制 (无模型)

注意: SeedVR2 模型仅支持 NVIDIA CUDA GPU 推理，不支持 CPU 推理。
"""

import contextlib
import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

# 环境变量: 防止 diffusers/huggingface 尝试联网导致卡住
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bin.integrated_app.engine_interface import RestoreEngine, RestoreResult  # noqa: E402
from bin.integrated_app.exceptions import InferenceCancelledError  # noqa: E402
from bin.integrated_app.optimization.blockswap import apply_block_swap_to_dit, cleanup_blockswap  # noqa: E402
from bin.integrated_app.optimization.cache_manager import get_cache_manager  # noqa: E402
from bin.integrated_app.optimization.memory_manager import (  # noqa: E402
    clear_memory,
    clear_rope_lru_caches,
    release_model_memory,
)
from bin.integrated_app.video_processor import FFmpegWrapper, VideoProcessor  # noqa: E402

# 从子模块导入共享工具（阶段二A 重构）
from bin.integrated_app.engines._memory_utils import (  # noqa: E402
    DTYPE_CONVERSION_GC_INTERVAL,
    ImageInferenceConfig,
    _check_memory,
    _check_memory_before_load,
    _cleanup_cuda_cache,
    _estimate_model_size_gb,
    _force_release_memory,
    _log_memory,
)

# 导入管线 mixin（阶段二A 重构）
from bin.integrated_app.engines._dit_pipeline import _DitPipelineMixin  # noqa: E402
from bin.integrated_app.engines._image_pipeline import _ImagePipelineMixin  # noqa: E402
from bin.integrated_app.engines._vae_pipeline import _VAEPipelineMixin  # noqa: E402
from bin.integrated_app.engines._video_pipeline import _VideoPipelineMixin  # noqa: E402

logger = logging.getLogger(__name__)


class SeedVR2Engine(
    RestoreEngine,
    _VAEPipelineMixin,
    _DitPipelineMixin,
    _VideoPipelineMixin,
    _ImagePipelineMixin,
):
    """SeedVR2 视频/图像修复推理引擎 - 完整 4 阶段推理流水线实现

    继承自 RestoreEngine 抽象基类，实现 SeedVR2 模型的完整推理功能。
    采用延迟加载策略：启动时仅加载配置和文本嵌入(~1MB)，VAE/DiT 大模型
    在推理时按阶段加载，用完立即销毁，严格控制内存峰值。

    结构重构后，推理管线方法分布在以下 mixin 中:
    - ``_VAEPipelineMixin``: ``_vae_encode``, ``_vae_decode``
    - ``_DitPipelineMixin``: ``_generation_step``, ``_guided_generation_step``, ``_timestep_transform``, ``_get_text_embeds``, ``_get_condition``
    - ``_VideoPipelineMixin``: ``infer_video``, ``_infer_video_impl``, ``_build_video_transform``, ``_cut_videos``
    - ``_ImagePipelineMixin``: ``infer_image``, ``_infer_image_impl``, ``_prepare_image_input``, ``_postprocess_output``, ``infer_batch``

    本文件保留核心方法: ``__init__``, ``load_model``, ``unload_model``,
    ``_destroy_*``, ``_load_dit_model``, ``_load_vae_model``, ``_configure_diffusion``,
    ``is_loaded``, ``get_model_info``, ``estimate_vram_required`` 等。

    核心特性:
    - 4 阶段流水线: VAE编码 -> DiT采样 -> VAE解码 -> 后处理
    - 分阶段模型加载/销毁: 任何时刻内存中最多一个大模型
    - BlockSwap 动态块交换: 在 GPU/CPU 间动态交换 transformer 块，降低显存需求
    - Tiled VAE: 支持分块编解码处理高分辨率输入，自动 tile size 和 OOM 回退
    - 蒸馏/标准双模式: 蒸馏模式(1步, cfg=1.0)快速推理，标准模式(50步, cfg=7.5)高质量
    - 内存安全: 90% 阈值监控、加载前预检、推理取消机制
    - 后处理增强: LAB颜色校正、小波重建、锐化、文本修复、EXIF复制

    推理模式:
    - 蒸馏模式 (distilled): cfg_scale=1.0, steps=1, 配合噪声增强实现快速推理
    - 标准模式 (standard): cfg_scale=7.5, steps=50, Euler采样 + Classifier-Free Guidance

    Args:
        config (dict): 应用配置字典，包含 model、inference、postprocessing 等段
    """

'''

parts = [HEADER]

# Extract core methods
for start, end in CORE_METHODS:
    chunk = lines[start - 1 : end]  # 0-indexed
    parts.append("".join(chunk))
    # Ensure there's a blank line between methods
    if not chunk[-1].endswith("\n"):
        parts.append("\n")
    parts.append("\n")

content = "".join(parts)
Path(ENGINE_FILE).write_text(content, encoding="utf-8")
print(f"Wrote new seedvr2_engine.py: {content.count(chr(10))} lines")
