#!/usr/bin/env python3
"""SeedVR2 工具箱 - 模型管理器"""
import logging
import os

import torch

from bin.integrated_app.engines.seedvr2_engine import SeedVR2Engine
from bin.integrated_app.gpu_utils import check_vram_available, clear_gpu_cache, estimate_model_vram
from bin.integrated_app.model_registry import model_registry

logger = logging.getLogger(__name__)


class ModelManager:
    """管理 SeedVR2 模型的加载、卸载和切换"""

    def __init__(self, config: dict):
        self.config = config
        self.model_config = config.get("model", {})
        self._engine: SeedVR2Engine | None = None

    @property
    def is_loaded(self) -> bool:
        return model_registry.model_loaded

    @property
    def engine(self) -> SeedVR2Engine | None:
        return model_registry.get_engine()

    def get_model_info(self, size: str) -> dict | None:
        """获取指定大小模型的信息"""
        return self.model_config.get("models", {}).get(size)

    def get_pretrained_dir(self) -> str:
        """获取预训练模型目录"""
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pretrained_dir = self.model_config.get("pretrained_dir", "pretrained_models")
        return os.path.join(project_root, pretrained_dir)

    def check_model_exists(self, size: str, precision: str = None) -> bool:
        """检查模型文件是否存在

        Args:
            size: 模型大小 (3b/7b)
            precision: 精度 (fp16/fp8)，默认检查 fp16
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
        """根据显存大小推荐精度

        Args:
            model_size: 模型大小 (3b/7b)

        Returns:
            推荐的精度 ("fp16" / "fp8")
        """
        model_info = self.get_model_info(model_size)
        if not model_info:
            return "fp16"

        min_fp16_gb = model_info.get("min_vram_fp16_gb", 16)
        min_fp8_gb = model_info.get("min_vram_fp8_gb", 8)

        try:
            if torch.cuda.is_available():
                total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            else:
                total_vram_gb = 0
        except Exception:
            total_vram_gb = 0

        if total_vram_gb >= min_fp16_gb:
            return "fp16"
        elif total_vram_gb >= min_fp8_gb:
            return "fp8"
        else:
            logger.warning(f"显存 {total_vram_gb:.1f}GB 不足以运行 {model_size} 模型 (最低需要 {min_fp8_gb}GB)，推荐使用 FP8 精度")
            return "fp8"

    async def load_model(self, model_size: str | None = None, device: str | None = None,
                         precision: str | None = None) -> dict:
        """加载指定模型

        Args:
            model_size: 模型大小 (3b/7b)，默认使用配置中的 default_size
            device: 设备 (auto/cuda)，默认使用配置中的 device
            precision: 精度 (fp16/fp8)，默认根据显存自动选择

        Returns:
            包含加载结果的字典
        """
        if model_size is None:
            model_size = self.model_config.get("default_size", "3b")
        if device is None:
            device = self.model_config.get("device", "auto")
        if precision is None or precision == "auto":
            precision = self.get_recommended_precision(model_size)

        # GPU 可用性检查：SeedVR2 仅支持 NVIDIA GPU 推理
        from bin.integrated_app.gpu_backend import gpu_manager
        if not gpu_manager.is_gpu_available:
            raise RuntimeError(
                "SeedVR2 仅支持 NVIDIA GPU 推理，当前未检测到 NVIDIA GPU。"
                "请安装 NVIDIA GPU 并配置 CUDA 驱动以启用推理功能。"
            )

        # 如果已经加载了相同模型和精度，直接返回
        if (model_registry.model_loaded
                and model_registry.current_model_size == model_size
                and model_registry.current_precision == precision):
            logger.info(f"模型 {model_size}/{precision} 已加载，跳过")
            return {"status": "ok", "message": f"模型 {model_size}/{precision} 已加载",
                    "model_size": model_size, "precision": precision}

        # 检查模型配置
        model_cfg = self.get_model_info(model_size)
        if not model_cfg:
            raise ValueError(f"未知的模型大小: {model_size}")

        # 检查模型文件
        if not self.check_model_exists(model_size, precision):
            # 尝试回退到另一种精度
            fallback_precision = "fp16" if precision == "fp8" else "fp8"
            if self.check_model_exists(model_size, fallback_precision):
                logger.warning(f"{precision} 模型文件不存在，回退到 {fallback_precision}")
                precision = fallback_precision
            else:
                raise FileNotFoundError(
                    f"模型文件不存在: {model_cfg.get(f'checkpoint_{precision}', 'N/A')} "
                    f"和 {model_cfg.get(f'checkpoint_{fallback_precision}', 'N/A')}"
                )

        # 检查显存
        required_vram = estimate_model_vram(model_size, precision=precision)
        can_load, available_vram = check_vram_available(required_vram)
        if not can_load:
            logger.warning(f"显存不足: 需要 {required_vram}MB，可用 {available_vram}MB")
            if device == "auto" and precision == "fp16":
                # 尝试切换到 fp8 以减少显存需求
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

        # 创建引擎并加载
        engine = SeedVR2Engine(self.config)
        await engine.load_model(model_size=model_size, device=device, precision=precision)

        # 注册到全局注册中心
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
        """卸载当前模型"""
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

    async def switch_model(self, model_size: str, device: str | None = None,
                           precision: str | None = None) -> dict:
        """切换模型（先卸载再加载，失败则回滚）

        Args:
            model_size: 目标模型大小
            device: 设备
            precision: 精度 (fp16/fp8)

        Returns:
            包含切换结果的字典
        """
        if (model_registry.current_model_size == model_size
                and model_registry.model_loaded
                and (precision is None or model_registry.current_precision == precision)):
            return {"status": "ok", "message": f"模型 {model_size} 已加载", "model_size": model_size}

        # 保存当前状态用于回滚
        previous_size = model_registry.current_model_size
        previous_precision = model_registry.current_precision
        model_registry.get_engine()
        previous_loaded = model_registry.model_loaded

        # 卸载当前模型
        if previous_loaded:
            await self.unload_model()

        # 尝试加载新模型
        try:
            result = await self.load_model(model_size=model_size, device=device, precision=precision)
            return result
        except Exception as e:
            logger.error(f"切换模型失败: {e}")

            # 回滚：重新加载之前的模型
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
        """获取当前模型信息"""
        return model_registry.get_status()

    def get_status(self) -> dict:
        """获取模型管理器状态"""
        status = model_registry.get_status()
        status["available_models"] = list(self.model_config.get("models", {}).keys())
        return status
