#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""SeedVR2 - 模型管理器模块

本模块实现模型生命周期管理，负责 SeedVR2 模型的加载、卸载、切换和显存预检，
是应用层与推理引擎之间的协调层。

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, asyncio, PyTorch CUDA

模块职责:
- 模型配置解析与验证（从 config.yaml 读取模型路径、大小、精度配置）
- 智能精度推荐（根据可用显存自动选择 fp16/fp8）
- 模型文件存在性检查与缺失时的精度回退
- 显存预检与加载前的资源验证
- 模型加载/卸载/切换的完整生命周期管理
- 模型切换失败时的自动回滚机制
- 与 model_registry 集成，同步全局模型状态

设计原则:
- 容错设计: 模型文件缺失或显存不足时自动尝试回退方案
- 安全切换: 切换模型前保存状态，失败时自动回滚到之前的模型
- 幂等操作: 重复加载相同模型直接返回成功，不重复加载
- 显存保护: 加载前严格检查显存，避免 OOM 导致系统不稳定
"""

import logging
import os

import torch

from bin.integrated_app.engine_interface import RestoreEngine
from bin.integrated_app.engines.seedvr2_engine import SeedVR2Engine
from bin.integrated_app.gpu_utils import check_vram_available, clear_gpu_cache, estimate_model_vram
from bin.integrated_app.model_registry import model_registry

logger = logging.getLogger(__name__)


class ModelManager:
    """SeedVR2 模型生命周期管理器

    管理模型的加载、卸载、切换，提供显存预检、精度推荐、文件验证等功能。
    通过 model_registry 维护全局模型状态，支持 SSE 状态推送。

    核心功能:
    - 智能精度推荐: 根据 GPU 显存自动选择 fp16 或 fp8
    - 显存预检: 加载前估算显存需求，检查是否有足够资源
    - 自动回退: 请求的精度文件不存在时自动尝试另一种精度
    - 安全切换: 切换模型失败时自动回滚到之前的模型
    - 状态同步: 所有状态变更自动同步到 model_registry

    Attributes:
        config (dict): 应用配置字典（从 config.yaml 加载）
        model_config (dict): 模型配置子字典
    """

    def __init__(self, config: dict):
        """初始化模型管理器

        Args:
            config: 完整的应用配置字典，应包含 "model" 键下的模型配置，
                    包括模型路径、可用模型大小、默认参数等
        """
        self.config = config
        self.model_config = config.get("model", {})
        self._engine: RestoreEngine | None = None

    @property
    def is_loaded(self) -> bool:
        """检查模型是否已加载

        Returns:
            bool: 模型已加载并可用于推理返回 True，否则返回 False

        Note:
            状态直接从全局 model_registry 获取，保证线程安全
        """
        return model_registry.model_loaded

    @property
    def engine(self) -> RestoreEngine | None:
        """获取当前引擎实例

        Returns:
            RestoreEngine | None: 当前激活的引擎实例，未加载时为 None

        Note:
            引擎引用从全局 model_registry 获取，确保始终是最新实例
        """
        return model_registry.get_engine()

    def get_model_info(self, size: str) -> dict | None:
        """获取指定大小模型的配置信息

        Args:
            size: 模型大小标识，如 "3b"、"7b"

        Returns:
            dict | None: 模型配置字典，包含 checkpoint 路径、显存需求等信息；
                        未找到对应大小的模型时返回 None
        """
        return self.model_config.get("models", {}).get(size)

    def get_pretrained_dir(self) -> str:
        """获取预训练模型根目录的绝对路径

        根据 model_source_mode 配置解析模型根目录:
        - portable 模式（默认）: {project_root}/{pretrained_dir}
        - shared 模式: 使用 shared_models_root 指定的外部共享目录

        Returns:
            str: 预训练模型目录的绝对路径
        """
        from bin.integrated_app.config_models import get_pretrained_root

        return get_pretrained_root(self.model_config)

    def check_model_exists(self, size: str, precision: str | None = None) -> bool:
        """检查指定模型文件是否存在

        验证指定大小和精度的模型 checkpoint 文件是否存在于文件系统中。

        Args:
            size: 模型大小标识 (如 "3b", "7b")
            precision: 模型精度 (如 "fp16", "fp8")，None 时使用配置中的默认精度

        Returns:
            bool: 模型文件存在返回 True，否则返回 False
        """
        model_info = self.get_model_info(size)
        if not model_info:
            return False

        pretrained_dir = self.get_pretrained_dir()
        if precision is None:
            precision = self.model_config.get("default_precision", "fp16")
        checkpoint_key = f"checkpoint_{precision}"
        checkpoint = model_info.get(checkpoint_key) or model_info.get("checkpoint_fp16", "")
        checkpoint_path = os.path.join(pretrained_dir, checkpoint)
        return os.path.exists(checkpoint_path)

    def get_recommended_precision(self, model_size: str) -> str:
        """根据 GPU 显存大小推荐最佳精度

        检测 CUDA 设备的总显存，与模型的最小显存需求比较，
        推荐 fp16（显存充足时）或 fp8（显存有限时）。

        Args:
            model_size: 模型大小标识 (如 "3b", "7b")

        Returns:
            str: 推荐的精度标识，"fp16" 或 "fp8"

        Note:
            - fp16 提供更好的推理质量，但需要更多显存
            - fp8 显存占用约为 fp16 的一半，质量略有下降
            - 即使显存不足也返回 fp8，由上层决定是否允许加载
        """
        model_info = self.get_model_info(model_size)
        if not model_info:
            return "fp16"

        min_fp16_gb = model_info.get("min_vram_fp16_gb", 16)
        min_fp8_gb = model_info.get("min_vram_fp8_gb", 8)

        try:
            if torch.cuda.is_available():
                total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            else:
                total_vram_gb = 0
        except Exception:
            total_vram_gb = 0

        if total_vram_gb >= min_fp16_gb:
            return "fp16"
        elif total_vram_gb >= min_fp8_gb:
            return "fp8"
        else:
            logger.warning(
                f"显存 {total_vram_gb:.1f}GB 不足以运行 {model_size} 模型 (最低需要 {min_fp8_gb}GB)，推荐使用 FP8 精度"
            )
            return "fp8"

    async def load_model(
        self, model_size: str | None = None, device: str | None = None, precision: str | None = None
    ) -> dict:
        """加载指定模型到 GPU

        完整的模型加载流程，包含参数验证、GPU 检查、文件检查、显存预检、
        精度回退、引擎创建、状态同步等步骤。

        Args:
            model_size: 模型大小 (如 "3b", "7b")，None 时使用配置中的 default_size
            device: 推理设备 ("auto"/"cuda")，None 时使用配置中的 device
            precision: 模型精度 ("fp16"/"fp8"/"auto")，None 或 "auto" 时根据显存自动选择

        Returns:
            dict: 加载结果字典，包含:
                - status: "ok" 表示成功
                - message: 人类可读的状态消息
                - model_size: 实际加载的模型大小
                - precision: 实际使用的精度
                - device: 使用的设备

        Raises:
            RuntimeError: 未检测到 NVIDIA GPU（SeedVR2 仅支持 CUDA）
            ValueError: 指定了未知的模型大小
            FileNotFoundError: 模型 checkpoint 文件不存在（fp16 和 fp8 都不存在）
            MemoryError: 显存不足无法加载模型（即使尝试 fp8 回退也不足）
        """
        if model_size is None:
            model_size = self.model_config.get("default_size", "3b")
        if device is None:
            device = self.model_config.get("device", "auto")
        if precision is None:
            precision = self.model_config.get("default_precision", "fp16")
        if precision == "auto":
            precision = self.get_recommended_precision(model_size)

        # Check if the same model is already loaded BEFORE the GPU check.
        # This allows returning the "already loaded" short-circuit even in
        # CPU-only / no-GPU environments (e.g. CI, unit tests), avoiding a
        # spurious RuntimeError when the model is already in memory.
        if (
            model_registry.model_loaded
            and model_registry.current_model_size == model_size
            and model_registry.current_precision == precision
        ):
            logger.info(f"模型 {model_size}/{precision} 已加载，跳过")
            return {
                "status": "ok",
                "message": f"模型 {model_size}/{precision} 已加载",
                "model_size": model_size,
                "precision": precision,
            }

        from bin.integrated_app.gpu_backend import gpu_manager

        if not gpu_manager.is_gpu_available:
            raise RuntimeError(
                "SeedVR2 仅支持 NVIDIA GPU 推理，当前未检测到 NVIDIA GPU。"
                "请安装 NVIDIA GPU 并配置 CUDA 驱动以启用推理功能。"
            )

        model_cfg = self.get_model_info(model_size)
        if not model_cfg:
            raise ValueError(f"未知的模型大小: {model_size}")

        if not self.check_model_exists(model_size, precision):
            fallback_precision = "fp16" if precision == "fp8" else "fp8"
            if self.check_model_exists(model_size, fallback_precision):
                logger.warning(f"{precision} 模型文件不存在，回退到 {fallback_precision}")
                precision = fallback_precision
            else:
                raise FileNotFoundError(
                    f"模型文件不存在: {model_cfg.get(f'checkpoint_{precision}', 'N/A')} "
                    f"和 {model_cfg.get(f'checkpoint_{fallback_precision}', 'N/A')}"
                )

        required_vram = estimate_model_vram(model_size, precision=precision)
        can_load, available_vram = check_vram_available(required_vram)
        if not can_load:
            logger.warning(f"显存不足: 需要 {required_vram}MB，可用 {available_vram}MB")
            if device == "auto" and precision == "fp16":
                fp8_vram = estimate_model_vram(model_size, precision="fp8")
                can_load_fp8, available_fp8 = check_vram_available(fp8_vram)
                if can_load_fp8 and self.check_model_exists(model_size, "fp8"):
                    logger.warning("尝试切换到 FP8 精度以减少显存需求")
                    precision = "fp8"
                else:
                    raise MemoryError(
                        f"显存不足: 需要 {required_vram}MB，可用 {available_vram}MB。"
                        f"SeedVR2 仅支持 NVIDIA GPU 推理，不支持 CPU。"
                    )
            else:
                raise MemoryError(
                    f"显存不足: 需要 {required_vram}MB，可用 {available_vram}MB。"
                    f"SeedVR2 仅支持 NVIDIA GPU 推理，不支持 CPU。"
                )

        logger.info(f"正在加载模型: {model_cfg.get('name', model_size)}/{precision}, 设备: {device}")

        engine = SeedVR2Engine(self.config)
        await engine.load_model(model_size=model_size, device=device, precision=precision)

        model_registry.set_engine(engine)
        self._engine = engine

        logger.info(f"模型加载完成: {model_size}/{precision}")
        return {
            "status": "ok",
            "message": f"模型 {model_size}/{precision} 加载成功",
            "model_size": model_size,
            "precision": precision,
            "device": device,
        }

    async def unload_model(self) -> dict:
        """卸载当前模型并释放所有 GPU/CPU 资源

        执行完整的卸载流程: 调用引擎卸载方法、清除 registry 中的引擎引用、
        清空 GPU 缓存。

        Returns:
            dict: 卸载结果字典，包含 status 和 message 字段

        Note:
            - 如果没有已加载的模型，直接返回成功，不报错
            - 卸载后 model_registry 状态会被重置为未加载
            - 会触发 GPU 缓存清理，尽力释放显存
        """
        if not model_registry.model_loaded:
            logger.info("没有已加载的模型")
            return {"status": "ok", "message": "没有已加载的模型"}

        engine = model_registry.get_engine()
        if engine is not None:
            logger.info(f"正在卸载模型: {model_registry.current_model_size}")
            await engine.unload_model()

        model_registry.clear_engine()
        self._engine = None
        clear_gpu_cache()

        logger.info("模型已卸载，显存已释放")
        return {"status": "ok", "message": "模型已卸载"}

    async def switch_model(self, model_size: str, device: str | None = None, precision: str | None = None) -> dict:
        """安全切换模型（先卸载旧模型，再加载新模型，失败则回滚）

        切换流程:
        1. 如果目标模型已加载，直接返回成功
        2. 保存当前模型状态用于回滚
        3. 卸载当前模型（如果已加载）
        4. 尝试加载新模型
        5. 如果加载失败，尝试回滚到之前的模型
        6. 如果回滚也失败，清除引擎状态

        Args:
            model_size: 目标模型大小
            device: 目标设备，None 时使用默认值
            precision: 目标精度，None 时自动推荐

        Returns:
            dict: 切换结果字典，格式同 load_model() 返回值

        Raises:
            RuntimeError: 切换失败且回滚也失败时抛出，包含原始错误信息

        Note:
            - 回滚机制确保切换失败时系统不会处于无模型可用的状态
            - 如果回滚时重新加载之前的模型也失败，会清除引擎状态并记录错误
        """
        if (
            model_registry.current_model_size == model_size
            and model_registry.model_loaded
            and (precision is None or model_registry.current_precision == precision)
        ):
            return {"status": "ok", "message": f"模型 {model_size} 已加载", "model_size": model_size}

        previous_size = model_registry.current_model_size
        previous_precision = model_registry.current_precision
        model_registry.get_engine()
        previous_loaded = model_registry.model_loaded

        if previous_loaded:
            await self.unload_model()

        try:
            result = await self.load_model(model_size=model_size, device=device, precision=precision)
            return result
        except Exception as e:
            logger.error(f"切换模型失败: {e}")

            if previous_loaded and previous_size is not None:
                logger.info(f"正在回滚到之前的模型: {previous_size}")
                try:
                    await self.load_model(model_size=previous_size, precision=previous_precision)
                    logger.info(f"已回滚到模型: {previous_size}")
                except Exception as rollback_err:
                    logger.error(f"回滚失败: {rollback_err}")
                    model_registry.clear_engine()

            raise RuntimeError(f"切换模型失败: {e}，已回滚到之前的模型") from e

    def get_current_model_info(self) -> dict:
        """获取当前已加载模型的状态信息

        Returns:
            dict: 模型状态字典，直接从 model_registry.get_status() 获取，包含:
                - model_loaded: bool - 是否已加载
                - current_model_size: str | None - 当前模型大小
                - current_precision: str | None - 当前精度
                - model_info: dict - 模型详细信息
        """
        return model_registry.get_status()

    def get_status(self) -> dict:
        """获取模型管理器的完整状态

        在 model_registry 状态基础上增加可用模型列表。

        Returns:
            dict: 完整状态字典，包含 model_registry 的所有字段，
                 以及 "available_models" 键列出所有支持的模型大小
        """
        status = model_registry.get_status()
        status["available_models"] = list(self.model_config.get("models", {}).keys())
        return status
