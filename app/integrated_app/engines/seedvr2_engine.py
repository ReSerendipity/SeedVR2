# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""SeedVR2 - SeedVR2 视频/图像修复推理引擎核心实现

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
import gc
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
from omegaconf import DictConfig

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# 导入管线 mixin（阶段二A 重构）
from app.integrated_app.engines._dit_pipeline import _DitPipelineMixin  # noqa: E402
from app.integrated_app.engines._image_pipeline import _ImagePipelineMixin  # noqa: E402

# 从子模块导入共享工具（阶段二A 重构）
from app.integrated_app.engines._memory_utils import (  # noqa: E402
    ImageInferenceConfig,  # noqa: F401 — re-exported for backward compat
    _check_memory,
    _check_memory_before_load,
    _cleanup_cuda_cache,
    _force_release_memory,
    _log_memory,
)
from app.integrated_app.engines._vae_pipeline import _VAEPipelineMixin  # noqa: E402
from app.integrated_app.engines._video_pipeline import _VideoPipelineMixin  # noqa: E402
from app.integrated_app.exceptions import InferenceCancelledError  # noqa: E402
from app.integrated_app.optimization.gpu.blockswap import apply_block_swap_to_dit, cleanup_blockswap  # noqa: E402
from app.integrated_app.optimization.gpu.memory_manager import (  # noqa: E402
    clear_rope_lru_caches,
    release_model_memory,
)
from app.integrated_app.video_processor import FFmpegWrapper, VideoProcessor  # noqa: E402

logger = logging.getLogger(__name__)


class SeedVR2Engine(
    _VAEPipelineMixin,
    _DitPipelineMixin,
    _VideoPipelineMixin,
    _ImagePipelineMixin,
):
    """SeedVR2 视频/图像修复推理引擎 - 完整 4 阶段推理流水线实现

    实现 RestoreEngine 和 BatchRestoreEngine 协议（通过结构化类型/鸭子类型），
    无需显式继承 Protocol。isinstance(engine, RestoreEngine) 和
    isinstance(engine, BatchRestoreEngine) 运行时检查均通过。

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

    def __init__(self, config: dict):
        """初始化 SeedVR2 引擎实例

        初始化模型组件引用、状态变量、取消令牌和外部工具。
        注意: __init__ 不加载大模型权重，仅初始化状态和工具，
        实际模型加载通过 load_model() 完成（延迟加载策略）。

        Args:
            config: 完整应用配置字典，从 config.yaml 加载
        """
        self.config = config
        self.dit = None
        self.vae = None
        self.pos_emb = None
        self.neg_emb = None
        self.schedule = None
        self.sampling_timesteps = None
        self.sampler = None
        self.model_size = None
        self.precision = "fp16"
        self.device = "cpu"
        self._loaded = False
        self._progress_callback = None
        self._model_config = None
        self._blockswap_active = False
        self._dit_checkpoint_path = None
        self._dit_model_size = None
        self._dit_precision = None
        self._cancel_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._ffmpeg = FFmpegWrapper()
        self._video_processor = VideoProcessor(self._ffmpeg)

    def set_progress_callback(self, callback: Callable):
        """设置进度回调函数

        用于推理过程中向外部报告进度。

        Args:
            callback: 回调函数，接收进度参数 (current_frame, total_frames, progress)
        """
        self._progress_callback = callback

    def _report_progress(
        self, current_frame: int = 0, total_frames: int = 0, progress: float = 0.0, message: str = ""
    ) -> None:
        """安全地调用进度回调，报告推理中间阶段进度（同步）。

        重要：此方法在推理工作线程中同步调用，回调函数 **必须是同步函数**。
        若注册 async 回调，其函数体不会被执行（仅产生未 await 的 coroutine），
        会导致进度永远停留在 0%。

        图像推理无逐帧进度，通过阶段标记（VAE编码/DiT采样/VAE解码/后处理）
        提供粗粒度进度反馈；视频推理通过逐帧 progress 实时上报。

        Args:
            current_frame: 当前阶段/帧序号。
            total_frames: 总阶段/帧数。
            progress: 0-100 的进度百分比。
            message: 阶段描述文本（透传到前端 SSE 的 message 字段）。
        """
        if self._progress_callback is None:
            return
        try:
            try:
                self._progress_callback(
                    current_frame=current_frame,
                    total_frames=total_frames,
                    progress=progress,
                    message=message,
                )
            except TypeError:
                # 兼容不接受 message 的旧签名回调
                self._progress_callback(
                    current_frame=current_frame,
                    total_frames=total_frames,
                    progress=progress,
                )
        except Exception as e:
            logger.debug(f"Progress callback 调用失败: {e}")

    # REFACTOR [E4-1]: 推理取消机制
    # task_queue 超时或用户主动取消时调用 request_cancel()，
    # 推理线程在阶段切换点通过 _check_cancelled() 主动检查并抛出 InferenceCancelledError

    def request_cancel(self) -> None:
        """请求取消当前推理任务

        由 TaskQueue 在超时或用户取消时调用（可能来自外部线程）。
        线程安全地设置 _cancel_event，推理线程在下一个阶段切换点检测到后退出。
        """
        with self._thread_lock:
            self._cancel_event.set()
        logger.info("推理取消信号已发送")

    def _check_cancelled(self, stage: str = "") -> None:
        """检查取消信号，若已取消则抛出 InferenceCancelledError

        在推理阶段切换点调用（阶段1/2/3/4 开始前），确保：
        - 不会在阶段中间退出导致 GPU 资源泄漏
        - 取消响应延迟 <= 一个阶段的执行时间（通常 < 30s）

        Args:
            stage: 当前阶段名称（用于日志）
        """
        with self._thread_lock:
            is_cancelled = self._cancel_event.is_set()
        if is_cancelled:
            logger.info(f"推理在阶段 '{stage}' 被取消")
            raise InferenceCancelledError(
                f"推理在阶段 '{stage}' 被取消",
                detail={"stage": stage},
            )

    def _reset_cancel_token(self) -> None:
        """重置取消令牌（在每次推理开始前调用）"""
        with self._thread_lock:
            self._cancel_event.clear()

    def _cleanup_after_error(self) -> None:
        """错误/取消后统一清理模型资源和 CUDA 缓存

        统一异常处理路径中的资源清理逻辑，确保 DiT/VAE 被销毁、CUDA 缓存被清空。
        """
        try:
            if self.dit is not None:
                self._destroy_dit()
        except Exception as e:
            logger.debug(f"清理 DiT 时出错: {e}")
        try:
            if self.vae is not None:
                self._destroy_vae()
        except Exception as e:
            logger.debug(f"清理 VAE 时出错: {e}")
        _cleanup_cuda_cache(deep=True)

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    async def load_model(self, model_size: str = "3b", device: str = "auto", precision: str = None) -> bool:
        """加载 SeedVR2 模型配置 (不加载大模型，推理时按阶段加载/销毁)
        注意: 仅支持 NVIDIA CUDA GPU，不支持 CPU 推理。

        严格按 ComfyUI 工作流策略:
        - 启动时只加载配置文件和文本嵌入 (~1MB)
        - VAE 和 DiT 在推理时按阶段加载，用完立即销毁
        - 任何时刻 RAM 中最多只有一个大模型
        """
        try:
            if precision is None:
                precision = self.config.get("model", {}).get("default_precision", "fp16")

            if self._loaded and self.model_size == model_size and self.precision == precision:
                logger.info(f"模型 {model_size}/{precision} 已加载，跳过")
                return True

            if self._loaded:
                await self.unload_model()

            self.device = self._resolve_device(device)
            logger.info(f"初始化 SeedVR2-{model_size.upper()}/{precision}，设备: {self.device}")

            # 获取模型配置
            model_cfg = self.config.get("model", {}).get("models", {}).get(model_size)
            if not model_cfg:
                raise ValueError(f"未找到模型配置: {model_size}")

            # 解析预训练模型根目录（支持 shared/portable 双模式）
            from app.integrated_app.config_models import get_pretrained_root

            model_cfg_dict = self.config.get("model", {})
            pretrained_root = get_pretrained_root(model_cfg_dict)
            pretrained_root_path = Path(pretrained_root)
            config_dir = model_cfg["config_dir"]

            # 加载 JSON 模型配置（config 文件始终从项目目录读取，不跟随 shared 模式）
            config_path = PROJECT_ROOT / config_dir / "config.json"
            if not config_path.exists():
                raise FileNotFoundError(f"模型配置文件未找到: {config_path}")
            with open(config_path) as f:
                self._model_config = json.load(f)

            # SHA256 完整性校验 (CWE-353 防御) — 在加载前验证权重文件哈希
            from app.integrated_app.security.integrity_check import verify_model_files

            integrity_results = verify_model_files(pretrained_root_path, model_cfg, precision)
            failed_checks = [k for k, v in integrity_results.items() if not v]
            if failed_checks:
                raise RuntimeError(
                    f"模型权重完整性校验失败 (CWE-353): {', '.join(failed_checks)}. "
                    f"文件可能已被篡改或投毒，拒绝加载。"
                )

            # 记录 DiT 路径 (延迟加载)
            checkpoint_key = f"checkpoint_{precision}"
            checkpoint_name = model_cfg.get(checkpoint_key) or model_cfg.get("checkpoint_fp16")
            checkpoint_path = pretrained_root_path / checkpoint_name
            if not checkpoint_path.exists():
                raise FileNotFoundError(f"DiT 模型文件未找到: {checkpoint_path}")
            self._dit_checkpoint_path = str(checkpoint_path)
            self._dit_model_size = model_size
            self._dit_precision = precision
            self.dit = None

            # 记录 VAE 路径 (延迟加载)
            vae_checkpoint_name = model_cfg["vae_checkpoint"]
            self._vae_checkpoint_path = str(pretrained_root_path / vae_checkpoint_name)
            if not os.path.exists(self._vae_checkpoint_path):
                raise FileNotFoundError(f"VAE 模型文件未找到: {self._vae_checkpoint_path}")
            self.vae = None

            # 加载文本嵌入 (~1MB，常驻内存)
            pos_emb_name = model_cfg.get("pos_emb", "pos_emb.pt")
            neg_emb_name = model_cfg.get("neg_emb", "neg_emb.pt")
            pos_path = pretrained_root_path / pos_emb_name
            neg_path = pretrained_root_path / neg_emb_name

            if pos_path.exists() and neg_path.exists():
                logger.info(f"加载文本嵌入: {pos_path}, {neg_path}")
                self.pos_emb = torch.load(str(pos_path), map_location="cpu", weights_only=True)  # nosemgrep: pickles-in-pytorch - torch.load(weights_only=True) 已启用安全模式，加载本地 pos 嵌入
                self.neg_emb = torch.load(str(neg_path), map_location="cpu", weights_only=True)  # nosemgrep: pickles-in-pytorch - torch.load(weights_only=True) 已启用安全模式，加载本地 neg 嵌入
            else:
                logger.warning("文本嵌入文件未找到，将使用零嵌入")
                self.pos_emb = None
                self.neg_emb = None

            # 配置扩散组件 (不需要模型实例)
            self._configure_diffusion(self._model_config, self.device)

            self.model_size = model_size
            self.precision = precision
            self._loaded = True
            logger.info(f"SeedVR2-{model_size.upper()}/{precision} 配置加载完成 (模型延迟加载)")
            return True

        except Exception as e:
            logger.error(f"模型配置加载失败: {e}")
            self._loaded = False
            raise

    def _destroy_module(
        self,
        model_attr: str,
        *,
        do_cleanup_blockswap: bool = False,
        cleanup_rope: bool = False,
        label: str = "模型",
        log_tag: str = "模型销毁后",
    ):
        """完全销毁模型模块，释放全部 VRAM 和 RAM

        统一 DiT/VAE 的销毁逻辑，避免重复代码。
        关键: 必须同时释放 CPU 上的参数 (BlockSwap offload) 和 GPU 上的激活，
        否则 RAM 不会释放，多次推理后内存爆满。

        Args:
            model_attr: 模型属性名（'dit' 或 'vae'）
            do_cleanup_blockswap: 是否清理 BlockSwap 状态（仅 DiT 需要）
            cleanup_rope: 是否清理 RoPE LRU 缓存（仅 DiT 需要）
            label: 日志标签
            log_tag: _log_memory 调用时的标签
        """
        model = getattr(self, model_attr, None)
        if model is None:
            return

        if do_cleanup_blockswap and self._blockswap_active:
            cleanup_blockswap(model)
            self._blockswap_active = False

        if cleanup_rope:
            for _name, module in model.named_modules():
                if hasattr(module, "get_axial_freqs") and hasattr(module.get_axial_freqs, "cache_clear"):
                    with contextlib.suppress(Exception):
                        module.get_axial_freqs.cache_clear()

        for param in list(model.parameters()):
            if param.numel() > 0:
                param.data = torch.empty(0, dtype=param.dtype, device="cpu")
            param.grad = None
        for buffer in list(model.buffers()):
            if buffer.numel() > 0:
                buffer.data = torch.empty(0, dtype=buffer.dtype, device="cpu")

        model.zero_grad(set_to_none=True)

        setattr(self, model_attr, None)
        del model

        _force_release_memory()
        if hasattr(torch._C, "_cuda_clearCublasWorkspaces"):
            with contextlib.suppress(Exception):
                torch._C._cuda_clearCublasWorkspaces()
        _log_memory(log_tag)
        logger.info(f"{label} 已完全销毁，VRAM+RAM 已释放")

    def _destroy_dit(self):
        """完全销毁 DiT 模型，释放全部 VRAM 和 RAM"""
        if self.dit is None:
            return
        self._destroy_module("dit", do_cleanup_blockswap=True, cleanup_rope=True, label="DiT 模型", log_tag="DiT销毁后")

    def _destroy_vae(self):
        """完全销毁 VAE 模型，释放 RAM 和 VRAM"""
        if self.vae is None:
            return
        self._destroy_module("vae", label="VAE 模型", log_tag="VAE销毁后")

    async def unload_model(self) -> bool:
        """卸载模型释放显存"""
        try:
            if self.dit is not None:
                if self._blockswap_active:
                    cleanup_blockswap(self.dit)
                    self._blockswap_active = False
                clear_rope_lru_caches(self.dit)
                release_model_memory(self.dit)
                self.dit = None
            if self.vae is not None:
                release_model_memory(self.vae)
                self.vae = None
            self.pos_emb = None
            self.neg_emb = None
            self.schedule = None
            self.sampling_timesteps = None
            self.sampler = None

            self._loaded = False
            self.model_size = None
            self.precision = None

            _cleanup_cuda_cache(deep=True)

            logger.info("模型已卸载，显存已释放")
            return True
        except Exception as e:
            logger.error(f"模型卸载失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 推理接口
    # ------------------------------------------------------------------

    def _get_inference_config(self, **kwargs) -> dict:
        """从 config.yaml 的 inference 部分读取推理参数，kwargs 可覆盖

        ComfyUI 工作流默认使用蒸馏模式 (1步, cfg=1.0):
        - 蒸馏模式: cfg_scale=1.0, steps=1, 噪声增强 base*0.1+randn*0.05
        - 标准模式: cfg_scale=7.5, steps=50
        """
        inf_cfg = self.config.get("inference", {})
        inference_mode = kwargs.get("inference_mode", inf_cfg.get("inference_mode", "distilled"))

        if inference_mode == "distilled":
            # ComfyUI 工作流默认: 1步蒸馏 + cfg=1.0
            default_cfg_scale = 1.0
            default_steps = 1
        else:  # standard (50步 Euler + CFG=7.5)
            default_cfg_scale = 7.5
            default_steps = 50

        return {
            "resolution": kwargs.get("resolution", inf_cfg.get("resolution", 2048)),
            "max_resolution": kwargs.get("max_resolution", inf_cfg.get("max_resolution", 0)),
            "batch_size": kwargs.get("batch_size", inf_cfg.get("batch_size", 1)),
            "uniform_batch_size": kwargs.get("uniform_batch_size", inf_cfg.get("uniform_batch_size", True)),
            "color_correction": kwargs.get("color_fix", inf_cfg.get("color_correction", "lab")),
            "temporal_overlap": kwargs.get("temporal_overlap", inf_cfg.get("temporal_overlap", 0)),
            "prepend_frames": kwargs.get("prepend_frames", inf_cfg.get("prepend_frames", 0)),
            "input_noise_scale": kwargs.get("input_noise_scale", inf_cfg.get("input_noise_scale", 0.0)),
            "latent_noise_scale": kwargs.get("latent_noise_scale", inf_cfg.get("latent_noise_scale", 0.0)),
            "seed": kwargs.get("seed", inf_cfg.get("seed", -1)),
            "attention_mode": kwargs.get(
                "attention_mode",
                inf_cfg.get("attention_mode", self.config.get("model", {}).get("attention_mode", "sdpa")),
            ),
            "enable_debug": kwargs.get("enable_debug", inf_cfg.get("enable_debug", False)),
            "inference_mode": inference_mode,
            "cfg_scale": kwargs.get("cfg_scale", default_cfg_scale),
            "cfg_rescale": kwargs.get("cfg_rescale", inf_cfg.get("cfg_rescale", 0.0)),
            "sample_steps": kwargs.get("sample_steps", default_steps),
            # Restoration guidance scale (Vivid-VR inspired): controls fidelity-realism tradeoff
            "restoration_guidance_scale": kwargs.get(
                "restoration_guidance_scale",
                inf_cfg.get("restoration_guidance_scale", 1.0),
            ),
            # Temporal segment processing for long videos (RVRT/DiffVSR inspired)
            "temporal_segment_size": kwargs.get(
                "temporal_segment_size",
                inf_cfg.get("temporal_segment_size", 0),
            ),
            "temporal_segment_overlap": kwargs.get(
                "temporal_segment_overlap",
                inf_cfg.get("temporal_segment_overlap", 8),
            ),
            # BlockSwap configuration (source: inference 配置段，勿从 model 段读取)
            "blocks_to_swap": kwargs.get(
                "blocks_to_swap",
                inf_cfg.get("blocks_to_swap", 32),
            ),
            "swap_io_components": kwargs.get(
                "swap_io_components",
                inf_cfg.get("swap_io_components", True),
            ),
            "offload_device": kwargs.get(
                "offload_device",
                inf_cfg.get("offload_device", "cpu"),
            ),
            # 模型跨任务缓存 (官方 cache_model 语义; 12GB 默认关闭)
            "cache_model": kwargs.get(
                "cache_model",
                inf_cfg.get("cache_model", False),
            ),
            # torch.compile 配置 (官方 SeedVR2 Torch Compile Settings 节点)
            "torch_compile": kwargs.get(
                "torch_compile",
                inf_cfg.get("torch_compile", {}),
            ),
        }

    def is_loaded(self) -> bool:
        """检查模型配置是否已加载完成

        注意: 这表示配置和文本嵌入已加载（延迟加载策略的"已加载"状态），
        DiT 和 VAE 大模型是在推理时按需加载/销毁的。

        Returns:
            bool: 模型配置已加载返回 True，否则返回 False
        """
        return self._loaded

    def get_model_info(self) -> dict:
        """获取当前模型的状态信息

        Returns:
            dict: 模型信息字典，包含:
                - loaded: bool - 是否已加载
                - model_size: str - 模型大小标识
                - precision: str - 模型精度
                - device: str - 推理设备
                - model_name: str - 人类可读的模型名称
                - blockswap_active: bool - BlockSwap 是否激活
        """
        if not self._loaded:
            return {"loaded": False}
        return {
            "loaded": True,
            "model_size": self.model_size,
            "precision": self.precision,
            "device": self.device,
            "model_name": f"SeedVR2-{self.model_size.upper()}/{self.precision}",
            "blockswap_active": self._blockswap_active,
        }

    def estimate_vram_required(self, model_size: str, resolution: tuple, precision: str = "fp16") -> int:
        """估算指定配置下推理所需的显存大小

        根据模型大小的基础显存需求和输入分辨率的像素因子，
        估算推理过程中的峰值显存占用。

        Args:
            model_size: 模型大小标识，如 "3b", "7b"
            resolution: 输入分辨率元组 (height, width)，单位为像素
            precision: 模型精度，"fp16" 或 "fp8"

        Returns:
            int: 估算所需显存，单位为 MB

        Note:
            估算基于 1080p (1920x1080) 分辨率的基准显存按比例缩放，
            分辨率低于 1080p 时使用基础显存需求（不缩小）。
        """
        model_cfg = self.config.get("model", {}).get("models", {}).get(model_size, {})
        if precision == "fp8":
            base_vram = model_cfg.get("min_vram_fp8_gb", 8) * 1024
        else:
            base_vram = model_cfg.get("min_vram_fp16_gb", 16) * 1024
        h, w = resolution
        pixel_factor = (h * w) / (1080 * 1920)
        return int(base_vram * max(1.0, pixel_factor))

    # ------------------------------------------------------------------
    # 内部方法 - 模型构建
    # ------------------------------------------------------------------

    def _resolve_device(self, device: str) -> str:
        """解析推理设备字符串

        将 "auto" 自动解析为可用的 CUDA 设备，或直接返回指定设备。
        SeedVR2 仅支持 NVIDIA CUDA GPU 推理，不支持 CPU。

        Args:
            device: 设备字符串，"auto" 表示自动选择，"cuda" 表示使用 GPU

        Returns:
            str: 解析后的设备字符串，当前仅返回 "cuda"

        Raises:
            RuntimeError: device="auto" 但 CUDA 不可用时抛出，提示需要 NVIDIA GPU
        """
        if device == "auto":
            if torch.cuda.is_available():
                return "cuda"
            raise RuntimeError("CUDA 不可用。SeedVR2 模型仅支持 NVIDIA GPU 推理，不支持 CPU。")
        return device

    def _load_dit_model(
        self,
        model_size: str,
        model_config: dict,
        checkpoint_path: str,
        precision: str,
        device: str,
        *,
        blocks_to_swap: int | None = None,
        swap_io_components: bool | None = None,
        offload_device: str | None = None,
        attention_mode: str | None = None,
        torch_compile_args: dict | None = None,
    ):
        """构建并加载 DiT 模型 - 严格对齐 ComfyUI 工作流参数

        REFACTOR [B1-1] [P3-1]: 显式参数化 BlockSwap 配置
        - 原实现从 self.config["model"] 读取 blocks_to_swap / swap_io_components / offload_device，
          要求调用方先修改 self.config 全局状态，导致配置污染
        - 改为通过显式参数接收，调用方直接传入请求级配置
        - 参数为 None 时回退到 self.config，保持向后兼容

        关键优化:
        - 使用 meta device 构建模型结构 (零内存占用)
        - 使用 assign=True 加载权重 (避免额外拷贝)
        - 逐个转换 dtype 避免内存翻倍
        - BlockSwap 参数通过显式参数传入 (从 inference 配置段读取，如 blocks_to_swap=32)
        - 每个关键步骤检查内存，超 90% 立即终止
        - 加载前预检: 估算模型大小，确认可用内存足够

        内存峰值估算 (3B fp16 -> bf16):
        - state_dict 加载: ~6GB (fp16)
        - dtype 逐个转换: ~6GB + 单个张量额外开销
        - meta 模型构建: 0
        - assign=True 加载: 0 (直接使用 state_dict 张量)
        - 总峰值: ~12GB (加载+转换期间)
        """
        from safetensors.torch import load_file

        # 预导入: 防止模块导入时卡住
        import common.distributed.advanced  # noqa: F401

        # 预先确定目标 dtype
        dit_config = model_config["dit"]
        dit_dtype = getattr(torch, dit_config.get("dtype", "bfloat16"))

        # ==================== 步骤1: 加载权重到 CPU ====================
        _check_memory_before_load(checkpoint_path, "DiT")
        _check_memory()
        _log_memory("DiT权重加载前")
        logger.info(f"加载 safetensors 权重: {checkpoint_path}")
        state_dict = load_file(checkpoint_path, device="cpu")
        _log_memory("DiT权重加载后(raw)")
        _check_memory()

        # FP8 反量化 (逐个转换，避免内存翻倍)
        if precision == "fp8":
            logger.info("FP8 权重反量化为 FP16...")
            for k in list(state_dict.keys()):
                v = state_dict[k]
                if isinstance(v, torch.Tensor) and v.dtype == torch.float8_e4m3fn:
                    state_dict[k] = v.to(torch.float16)
                    del v
            gc.collect()
            _check_memory()

        # 逐个转换为目标 dtype (避免同时存在两份权重的内存峰值)
        # 关键: 每转换一个张量就删除旧张量，并定期 GC
        converted_count = 0
        for k in list(state_dict.keys()):
            v = state_dict[k]
            if isinstance(v, torch.Tensor) and v.dtype != dit_dtype:
                state_dict[k] = v.to(dtype=dit_dtype)
                del v
                converted_count += 1
                # 每转换 50 个参数检查一次内存 + GC
                if converted_count % 50 == 0:
                    gc.collect()
                    _check_memory()
        if converted_count > 0:
            gc.collect()
            logger.info(f"已将 {converted_count} 个参数转换为 {dit_dtype}")

        _check_memory()
        _log_memory("DiT权重dtype转换后")

        # ==================== 步骤2: 构建 DiT 模型 (meta device) ====================
        num_layers = dit_config["num_layers"]

        # 展开短列表参数到 num_layers 长度
        window_method = dit_config.get("window_method")
        if isinstance(window_method, list) and len(window_method) < num_layers:
            repeats = num_layers // len(window_method)
            window_method = window_method * repeats
            remainder = num_layers - len(window_method)
            if remainder > 0:
                window_method = window_method + window_method[:remainder]
            logger.info(f"window_method 展开为 {len(window_method)} 个元素")

        with torch.device("meta"):
            if model_size == "3b":
                from model_lib.dit_v2.nadit import NaDiT

                model = NaDiT(
                    vid_in_channels=dit_config["vid_in_channels"],
                    vid_out_channels=dit_config["vid_out_channels"],
                    vid_dim=dit_config["vid_dim"],
                    vid_out_norm=dit_config.get("vid_out_norm"),
                    txt_in_dim=dit_config["txt_in_dim"],
                    txt_in_norm=dit_config.get("txt_in_norm"),
                    txt_dim=dit_config["txt_dim"],
                    emb_dim=dit_config["emb_dim"],
                    heads=dit_config["heads"],
                    head_dim=dit_config["head_dim"],
                    expand_ratio=dit_config["expand_ratio"],
                    norm=dit_config["norm"],
                    norm_eps=dit_config["norm_eps"],
                    ada=dit_config["ada"],
                    qk_bias=dit_config["qk_bias"],
                    qk_norm=dit_config["qk_norm"],
                    patch_size=dit_config["patch_size"],
                    num_layers=num_layers,
                    block_type=dit_config["block_type"],
                    mm_layers=dit_config.get("mm_layers", num_layers),
                    mlp_type=dit_config.get("mlp_type", "swiglu"),
                    msa_type=dit_config.get("msa_type"),
                    rope_type=dit_config.get("rope_type", "mmrope3d"),
                    rope_dim=dit_config.get("rope_dim", 128),
                    window=dit_config.get("window"),
                    window_method=window_method,
                    attention_mode=attention_mode or "sdpa",
                )
            elif model_size == "7b":
                from model_lib.dit.nadit import NaDiT

                model = NaDiT(
                    vid_in_channels=dit_config["vid_in_channels"],
                    vid_out_channels=dit_config["vid_out_channels"],
                    vid_dim=dit_config["vid_dim"],
                    txt_in_dim=dit_config["txt_in_dim"],
                    txt_dim=dit_config["txt_dim"],
                    emb_dim=dit_config["emb_dim"],
                    heads=dit_config["heads"],
                    head_dim=dit_config["head_dim"],
                    expand_ratio=dit_config["expand_ratio"],
                    norm=dit_config["norm"],
                    norm_eps=dit_config["norm_eps"],
                    ada=dit_config["ada"],
                    qk_bias=dit_config["qk_bias"],
                    qk_rope=dit_config.get("qk_rope", True),
                    qk_norm=dit_config["qk_norm"],
                    patch_size=dit_config["patch_size"],
                    num_layers=num_layers,
                    block_type=dit_config["block_type"],
                    shared_qkv=dit_config.get("shared_qkv", False),
                    shared_mlp=dit_config.get("shared_mlp", False),
                    mlp_type=dit_config.get("mlp_type", "normal"),
                    window=dit_config.get("window"),
                    window_method=window_method,
                )
            else:
                raise ValueError(f"未知模型大小: {model_size}")

        model.set_gradient_checkpointing(dit_config.get("gradient_checkpoint", True))

        # 诊断: 确认模型有 blocks 属性
        has_blocks = hasattr(model, "blocks")
        num_blocks = len(model.blocks) if has_blocks else 0
        logger.info(f"DiT 模型结构诊断: has_blocks={has_blocks}, num_blocks={num_blocks}")

        # ==================== 步骤3: 加载权重 (assign=True) ====================
        # assign=True 让模型直接使用 state_dict 中的张量，避免拷贝
        loading_info = model.load_state_dict(state_dict, strict=False, assign=True)
        # 立即删除 state_dict (模型已通过 assign=True 接管张量)
        del state_dict
        gc.collect()
        logger.info(
            f"DiT 加载信息: missing={len(loading_info.missing_keys)}, unexpected={len(loading_info.unexpected_keys)}"
        )

        # 手动初始化 meta buffers
        for _name, module in model.named_modules():
            for buffer_name, buffer in list(module.named_buffers(recurse=False)):
                if buffer.is_meta:
                    setattr(module, buffer_name, torch.zeros_like(buffer, device="cpu"))

        model.eval()

        _check_memory()
        _log_memory("DiT权重assign后")

        # VRAM optimization toolchain (CogVideo/FlashVSR inspired)
        try:
            from app.integrated_app.optimization.gpu.vram_toolchain import FP8Quantizer, XFormersIntegration

            # FP8 quantization
            fp8_enabled = self.config.get("inference", {}).get("fp8_enabled", False)
            if fp8_enabled:
                quantizer = FP8Quantizer()
                model = quantizer.quantize(model)
                logger.info("FP8 quantization applied")
            # xformers memory-efficient attention
            xformers_ok = XFormersIntegration.try_enable(model)
            if xformers_ok:
                logger.info("xformers memory-efficient attention enabled")
        except Exception as e:
            logger.debug(f"VRAM toolchain skipped: {e}")

        # ==================== 步骤4: 应用 BlockSwap (严格对齐 ComfyUI 工作流) ====================
        # REFACTOR [B1-1]: 显式参数优先，None 时回退到 self.config
        # 原实现总是从 self.config["model"] 读取 blocks_to_swap/swap_io_components/offload_device，
        # 要求调用方先修改 self.config 全局状态（_infer_image_impl 中曾通过 copy.deepcopy + 配置写入实现），
        # 这导致全局配置污染与并发安全问题
        # 改为显式参数优先：调用方直接传入请求级配置；None 时回退到 self.config 保持向后兼容
        # 注意: blocks_to_swap/swap_io_components/offload_device 位于 config.yaml 的 inference 段，
        # 从 model 段读取将永远命中默认值，导致配置不生效
        inf_cfg = self.config.get("inference", {})
        if blocks_to_swap is None:
            blocks_to_swap = inf_cfg.get("blocks_to_swap", dit_config.get("blocks_to_swap", 0))
        if swap_io_components is None:
            swap_io_components = inf_cfg.get("swap_io_components", dit_config.get("swap_io_components", False))
        if offload_device is None:
            offload_device = inf_cfg.get("offload_device", dit_config.get("offload_device", "cpu"))

        logger.info(
            f"BlockSwap 配置: blocks_to_swap={blocks_to_swap}, "
            f"swap_io_components={swap_io_components}, offload_device={offload_device}, "
            f"model_blocks={num_blocks}"
        )

        if blocks_to_swap > 0 or swap_io_components:
            logger.info(
                f"应用 BlockSwap: blocks_to_swap={blocks_to_swap}, "
                f"swap_io_components={swap_io_components}, offload_device={offload_device}"
            )
            apply_block_swap_to_dit(
                model=model,
                blocks_to_swap=blocks_to_swap,
                swap_io_components=swap_io_components,
                main_device=device,
                offload_device=offload_device,
                debug=False,
            )
            self._blockswap_active = True

            # 诊断: 验证 BlockSwap 确实生效
            blockswap_marker = getattr(model, "_blockswap_active", False)
            blockswap_config = getattr(model, "_block_swap_config", None)
            logger.info(f"BlockSwap 诊断: model._blockswap_active={blockswap_marker}, " f"config={blockswap_config}")

            if not blockswap_marker:
                logger.error(
                    "BlockSwap 未正确应用! 模型._blockswap_active=False，" "这会导致模型整体加载到 GPU，内存爆满!"
                )
                # 尝试手动设置
                model._blockswap_active = True

            logger.info("BlockSwap 已应用，模型将使用动态块交换")
        else:
            self._blockswap_active = False
            logger.warning(
                f"BlockSwap 未启用 (blocks_to_swap={blocks_to_swap}, "
                f"swap_io_components={swap_io_components})，"
                f"模型将整体加载到 GPU，可能内存不足!"
            )
            if device in ["cuda", self._resolve_device("auto")]:
                model.to(device)

        _check_memory()
        _log_memory("DiT BlockSwap后")

        # ==================== 步骤5: torch.compile (官方 Torch Compile Settings 节点) ====================
        # 可选加速: DiT 20-40% 提速; 需要 PyTorch 2.0+; 默认关闭 (更耗显存)
        if torch_compile_args and torch_compile_args.get("enabled", False):
            try:
                from app.integrated_app.optimization.gpu.vram_toolchain import (
                    CompileConfig,
                    CompileOptimizer,
                )

                compile_cfg = CompileConfig(
                    enabled=True,
                    mode=torch_compile_args.get("mode", "default"),
                    backend=torch_compile_args.get("backend", "inductor"),
                    fullgraph=torch_compile_args.get("fullgraph", False),
                    dynamic=torch_compile_args.get("dynamic", False),
                )
                optimizer = CompileOptimizer(compile_cfg)
                if optimizer.is_available():
                    model = optimizer.compile(model)
                    logger.info(f"DiT torch.compile 已应用: mode={compile_cfg.mode}")
                else:
                    logger.warning("torch.compile 不可用 (需要 PyTorch 2.0+)，跳过")
            except Exception as e:
                logger.warning(f"DiT torch.compile 应用失败，回退未编译: {e}")

        # DiT optimization reference (FlashVSR inspired)
        # LCSA sparse attention would be applied here when model supports it
        # Currently disabled as it requires model architecture changes

        num_params = sum(p.numel() for p in model.parameters())
        logger.info(f"DiT 参数数量: {num_params:,}, dtype={dit_dtype}, " f"blockswap={self._blockswap_active}")

        return model

    def _load_vae_model(
        self,
        model_config: dict,
        checkpoint_path: str,
        device: str,
        *,
        vae_tiled_config: dict | None = None,
        torch_compile_args: dict | None = None,
    ):
        """构建并加载 VAE 模型 - 严格对齐 ComfyUI HD 工作流参数

        REFACTOR [B1-1] [P3-1]: 显式参数化 VAE tiled 配置
        - 原实现从 self.config["model"]["vae"] 读取 tiled 参数，要求调用方先修改 self.config
        - 改为通过显式参数 vae_tiled_config 接收，调用方直接传入请求级配置
        - 参数为 None 时回退到 self.config，保持向后兼容

        ComfyUI 的 VAE 加载方式 (model_loader.py):
        1. 在 meta device 上构建模型结构 (零内存)
        2. 加载 safetensors 权重到 offload_device (CPU)
        3. 使用 assign=True 加载 (避免权重拷贝，零额外内存)
        4. 初始化 meta buffers
        5. 不做 model.to(dtype=...) 转换 (权重已在 state_dict 中转换)

        ComfyUI HD 工作流参数:
        - encode_tiled=true, decode_tiled=true, decode_tile_size=1024
        - offload_device=cpu
        """
        from safetensors.torch import load_file

        # 预导入: 防止 attn_video_vae 导入时卡住
        import common.distributed.advanced  # noqa: F401

        # 读取 VAE YAML 配置获取完整参数
        vae_config = model_config["vae"]
        from model_lib.video_vae_v3.modules.attn_video_vae import VideoAutoencoderKLWrapper

        vae_yaml_path = PROJECT_ROOT / vae_config.get("config", "model_lib/video_vae_v3/s8_c16_t4_inflation_sd3.yaml")
        vae_params = self._load_vae_yaml_config(vae_yaml_path)

        # REFACTOR [B1-1]: 显式参数优先，None 时回退到 self.config
        # 原实现总是从 self.config["model"]["vae"] 读取，要求调用方先污染全局配置
        # 改为显式参数优先：调用方直接传入请求级 vae_tiled_config；None 时回退到 self.config
        if vae_tiled_config is None:
            vae_cfg = self.config.get("model", {}).get("vae", {})
            vae_tiled_config = {
                "encode_tiled": vae_cfg.get("encode_tiled", True),
                "encode_tile_size": vae_cfg.get("encode_tile_size", 1024),
                "encode_tile_overlap": vae_cfg.get("encode_tile_overlap", 128),
                "decode_tiled": vae_cfg.get("decode_tiled", True),
                "decode_tile_size": vae_cfg.get("decode_tile_size", 1024),
                "decode_tile_overlap": vae_cfg.get("decode_tile_overlap", 128),
                "tile_debug": vae_cfg.get("tile_debug", False),
                "offload_device": vae_cfg.get("offload_device", "cpu"),
                "cache_model": vae_cfg.get("cache_model", True),
                "auto_tile_size": vae_cfg.get("auto_tile_size", True),
                "gaussian_blend": vae_cfg.get("gaussian_blend", True),
                "groupnorm_accumulate": vae_cfg.get("groupnorm_accumulate", True),
            }
        self._vae_tiled_config = vae_tiled_config
        logger.info(
            f"VAE tiled 配置: encode_tiled={self._vae_tiled_config['encode_tiled']}, "
            f"decode_tiled={self._vae_tiled_config['decode_tiled']}, "
            f"encode_tile_size={self._vae_tiled_config['encode_tile_size']}, "
            f"decode_tile_size={self._vae_tiled_config['decode_tile_size']}, "
            f"tile_overlap={self._vae_tiled_config['encode_tile_overlap']}"
        )

        block_out_channels = tuple(vae_params.get("block_out_channels", [128, 256, 512, 512]))
        down_block_types = tuple(vae_params.get("down_block_types", ["DownEncoderBlock3D"] * len(block_out_channels)))
        up_block_types = tuple(vae_params.get("up_block_types", ["UpDecoderBlock3D"] * len(block_out_channels)))

        # ==================== 步骤1: 在 meta device 上构建 VAE (零内存) ====================
        _check_memory_before_load(checkpoint_path, "VAE")
        _check_memory()
        _log_memory("VAE构建前")
        with torch.device("meta"):
            model = VideoAutoencoderKLWrapper(
                spatial_downsample_factor=vae_params.get("spatial_downsample_factor", 8),
                temporal_downsample_factor=vae_params.get("temporal_downsample_factor", 4),
                in_channels=vae_params.get("in_channels", 3),
                out_channels=vae_params.get("out_channels", 3),
                down_block_types=down_block_types,
                up_block_types=up_block_types,
                block_out_channels=block_out_channels,
                layers_per_block=vae_params.get("layers_per_block", 2),
                latent_channels=vae_params.get("latent_channels", 16),
                use_quant_conv=vae_params.get("use_quant_conv", False),
                use_post_quant_conv=vae_params.get("use_post_quant_conv", False),
                temporal_scale_num=vae_params.get("temporal_scale_num", 2),
                inflation_mode=vae_params.get("inflation_mode", "pad"),
                slicing_sample_min_size=vae_params.get("slicing_sample_min_size", 4),
                freeze_encoder=vae_config.get("freeze_encoder", False),
            )

        # ==================== 步骤2: 加载权重到 CPU (offload_device) ====================
        _log_memory("VAE meta构建后")
        _check_memory()
        logger.info(f"加载 VAE safetensors 权重: {checkpoint_path}")
        state_dict = load_file(checkpoint_path, device="cpu")
        _log_memory("VAE权重加载后(raw)")
        _check_memory()

        # 逐个转换为目标 dtype (避免内存翻倍)
        # ComfyUI: VAE YAML 默认 dtype=float16, 但会被 compute_dtype 覆盖为 bfloat16
        vae_dtype = getattr(torch, vae_config.get("dtype", "bfloat16"))
        converted_count = 0
        for k in list(state_dict.keys()):
            v = state_dict[k]
            if isinstance(v, torch.Tensor) and v.dtype != vae_dtype:
                state_dict[k] = v.to(dtype=vae_dtype)
                del v
                converted_count += 1
                if converted_count % 50 == 0:
                    gc.collect()
                    _check_memory()
        if converted_count > 0:
            gc.collect()
            logger.info(f"VAE: 已将 {converted_count} 个参数转换为 {vae_dtype}")

        _check_memory()
        _log_memory("VAE权重dtype转换后")

        # ==================== 步骤3: 使用 assign=True 加载 (避免权重拷贝) ====================
        loading_info = model.load_state_dict(state_dict, strict=False, assign=True)
        del state_dict
        gc.collect()
        logger.info(
            f"VAE 加载信息: missing={len(loading_info.missing_keys)}, unexpected={len(loading_info.unexpected_keys)}"
        )

        # 初始化 meta buffers (与 ComfyUI model_loader.py 一致)
        for _name, module in model.named_modules():
            for buffer_name, buffer in list(module.named_buffers(recurse=False)):
                if buffer.is_meta:
                    setattr(module, buffer_name, torch.zeros_like(buffer, device="cpu"))

        model.requires_grad_(False).eval()

        # 设置 causal slicing (与 ComfyUI 工作流一致)
        slicing_cfg = vae_config.get("slicing", {})
        if slicing_cfg:
            model.set_causal_slicing(
                split_size=slicing_cfg.get("split_size"),
                memory_device=slicing_cfg.get("memory_device", "same"),
            )

        # 设置内存限制 (与 ComfyUI 工作流一致)
        memory_limit_cfg = vae_config.get("memory_limit", {})
        if memory_limit_cfg and hasattr(model, "set_memory_limit"):
            model.set_memory_limit(**memory_limit_cfg)

        # 注意: 不做 model.to(dtype=vae_dtype)，权重已在 state_dict 中转换
        # ComfyUI 也不做这一步，model.to(dtype=...) 会创建 dtype 转换副本导致内存翻倍

        # torch.compile (官方 VAE 节点: 15-25% 提速; 默认关闭)
        if torch_compile_args and torch_compile_args.get("enabled", False):
            try:
                from app.integrated_app.optimization.gpu.vram_toolchain import (
                    CompileConfig,
                    CompileOptimizer,
                )

                compile_cfg = CompileConfig(
                    enabled=True,
                    mode=torch_compile_args.get("mode", "default"),
                    backend=torch_compile_args.get("backend", "inductor"),
                    fullgraph=torch_compile_args.get("fullgraph", False),
                    dynamic=torch_compile_args.get("dynamic", False),
                )
                optimizer = CompileOptimizer(compile_cfg)
                if optimizer.is_available():
                    model = optimizer.compile(model)
                    logger.info(f"VAE torch.compile 已应用: mode={compile_cfg.mode}")
                else:
                    logger.warning("torch.compile 不可用 (需要 PyTorch 2.0+)，跳过")
            except Exception as e:
                logger.warning(f"VAE torch.compile 应用失败，回退未编译: {e}")

        _check_memory()
        _log_memory("VAE权重加载后")

        return model

    def _load_vae_yaml_config(self, yaml_path: Path) -> dict:
        """加载 VAE YAML 配置文件

        读取并解析 VAE 架构配置文件（包含通道数、层数、下采样因子等参数）。
        文件不存在或解析失败时返回空字典，使用默认参数。

        Args:
            yaml_path: VAE YAML 配置文件路径

        Returns:
            dict: 解析后的配置字典，失败时返回空字典
        """
        if not yaml_path.exists():
            logger.warning(f"VAE YAML 配置未找到: {yaml_path}，使用默认参数")
            return {}

        try:
            import yaml as _yaml

            with open(str(yaml_path), encoding="utf-8") as f:
                params = _yaml.safe_load(f)
            return params if isinstance(params, dict) else {}
        except Exception as e:
            logger.warning(f"加载 VAE YAML 配置失败: {e}，使用默认参数")
            return {}

    # ------------------------------------------------------------------
    # 内部方法 - 扩散配置
    # ------------------------------------------------------------------

    def _configure_diffusion(self, model_config: dict, device: str):
        """配置扩散采样组件

        根据模型配置初始化噪声调度器（schedule）、采样时间步（timesteps）
        和采样器（sampler），这些组件是 DiT 采样的核心依赖。

        Args:
            model_config: 模型配置字典，应包含 "diffusion" 段
            device: 设备字符串，如 "cuda"

        Note:
            此方法会覆盖 self.schedule、self.sampling_timesteps、self.sampler，
            在每次采样前会根据 cfg_scale 和 sample_steps 重新配置。
        """
        from common.diffusion import (
            create_sampler_from_config,
            create_sampling_timesteps_from_config,
            create_schedule_from_config,
        )

        diff_cfg = model_config["diffusion"]
        # 转换为 OmegaConf DictConfig
        schedule_cfg = DictConfig(diff_cfg["schedule"])
        sampler_cfg = DictConfig(diff_cfg["sampler"])
        timesteps_cfg = DictConfig(diff_cfg["timesteps"]["sampling"])

        self.schedule = create_schedule_from_config(schedule_cfg, device)
        self.sampling_timesteps = create_sampling_timesteps_from_config(timesteps_cfg, self.schedule, device)
        self.sampler = create_sampler_from_config(sampler_cfg, self.schedule, self.sampling_timesteps)
        logger.info(
            f"扩散组件配置完成: schedule={diff_cfg['schedule']['type']}, "
            f"sampler={diff_cfg['sampler']['type']}, "
            f"steps={diff_cfg['timesteps']['sampling']['steps']}"
        )

    # ------------------------------------------------------------------
    # 内部方法 - VAE 编解码
    # ------------------------------------------------------------------
