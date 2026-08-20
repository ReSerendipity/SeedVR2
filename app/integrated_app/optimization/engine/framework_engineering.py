"""框架 / 工程化模块

所属项目: SeedVR2 (SeedVR2 视频/图像修复应用)
核心技术栈: Python, PyTorch, PyYAML, 配置管理, 多GPU推理, 数据预取, pybind11

本模块提供框架级工程化能力的参考实现，整合多个竞品项目的工程最佳实践，
包括配置管理、检查点恢复、多GPU并行推理、数据预取、模型自描述、
C++绑定接口等基础设施能力。

主要功能:
- YAMLConfigManager: BasicSR风格YAML配置驱动+CLI参数覆盖
- ConfigDrivenInstantiator: DiffBIR风格配置驱动模型动态实例化
- AutoResumeManager: BasicSR风格自动检查点恢复（断点续训/续推）
- MultiGPUInference: CogVideo xDiT风格多GPU并行推理框架（Ulysses/Ring/Pipeline/Data）
- CUDAPrefetcher/CPUPrefetcher: BasicSR风格CPU/CUDA数据预取器
- ModelSelfDescriptor: waifu2x风格模型自描述属性元数据
- PyBindInterface: Anime4KCPP风格pybind11零拷贝C++扩展调用接口
- HydraStyleConfigManager: Fast-SRGAN风格Hydra配置管理参考
- 工厂函数: 快速创建默认配置的工程组件

参考竞品与设计来源:
- BasicSR: YAML 配置驱动 + CLI 覆盖 (P2)
- DiffBIR: OmegaConf + instantiate_from_config 配置驱动模型实例化 (P2)
- BasicSR: auto_resume 自动检查点恢复 (P2)
- CogVideo: xDiT xFuser Ulysses/Ring Attention 多 GPU 推理 (P3)
- BasicSR: CPU/CUDA Prefetcher 数据预取 (P2)
- waifu2x: w2nn* 自描述属性元数据模式 (P2)
- Anime4KCPP: pybind11 零拷贝 NumPy 传递 (P2)
- Fast-SRGAN: Hydra 配置管理 (P3)
"""

import copy
import logging
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import torch
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 安全模型加载辅助函数 - 防御 pickle 反序列化 RCE
# ---------------------------------------------------------------------------


def _safe_torch_load(
    path: str,
    map_location: str = "cpu",
    *,
    allow_pickle_fallback: bool = False,
    purpose: str = "model",
) -> Any:
    """安全的 torch.load 包装器，优先使用 weights_only=True 防御 pickle RCE。

    安全策略:
        1. 首选 weights_only=True (只允许 Tensor/基本类型容器，无任意 Python 对象反序列化)
        2. 若加载失败且 allow_pickle_fallback=True，回退到 weights_only=False 并记录
           严重安全警告 - 仅当加载包含非 Tensor 元数据的遗留 checkpoint 时才需要回退
        3. 回退前记录告警日志，提醒用户模型文件来源不受信时存在 RCE 风险

    Args:
        path: 模型/checkpoint 文件路径
        map_location: 设备映射，默认 "cpu"
        allow_pickle_fallback: 是否允许在 weights_only 失败后回退到 pickle 模式
        purpose: 用于告警消息的描述性标签 ("checkpoint" / "metadata" / etc.)

    Returns:
        加载后的 state_dict / checkpoint 对象

    Security Note:
        CWE-502: pickle 反序列化可能导致任意代码执行。weights_only=True 强制
        torch 使用受限 unpickler，仅允许 Tensor、基本数值类型、字符串、list/dict/tuple
        等安全容器。仅当确定模型文件来源 100% 可信时才启用 pickle 回退。
    """
    # Step 1: 安全模式优先
    try:
        return torch.load(path, map_location=map_location, weights_only=True)  # nosemgrep: pickles-in-pytorch - 安全包装器 Step1：weights_only=True 受限 unpickler
    except Exception as safe_err:
        if not allow_pickle_fallback:
            logger.error(
                f"[SECURITY] {purpose} 安全加载(weights_only=True)失败: {safe_err}. "
                f"拒绝回退到 pickle 模式。请将模型转换为 safetensors 格式或使用可信来源的 weights_only 兼容格式。"
            )
            raise

    # Step 2: 仅显式允许时才回退，记录严重安全告警
    logger.warning(
        f"[SECURITY CRITICAL] {purpose} 正在使用 pickle 模式 (weights_only=False) 加载: {path}\n"
        f"    这可能导致任意代码执行 (CWE-502)。请确保该文件来源 100% 可信。\n"
        f"    建议: 迁移到 safetensors 格式以彻底消除 pickle 风险。"
    )
    return torch.load(path, map_location=map_location, weights_only=False)  # nosemgrep: pickles-in-pytorch - allow_pickle_fallback 门控回退（默认 False），回退前打 [SECURITY CRITICAL] 日志


# ---------------------------------------------------------------------------
# 1. YAML 配置驱动 + CLI 覆盖 (BasicSR P2)
# ---------------------------------------------------------------------------


@dataclass
class YAMLConfigOptions:
    """YAML 配置选项

    参考 BasicSR 的配置系统设计:
    - YAML 文件定义所有配置项
    - CLI 参数可覆盖 YAML 中的值
    - 支持嵌套键路径 (e.g., "model.cfg_scale=5.0")
    - 支持配置继承 (base_config + override)

    BasicSR 的配置层次:
    1. 默认值 (代码中定义)
    2. base YAML (通用基础配置)
    3. override YAML (任务特定配置)
    4. CLI 参数 (运行时覆盖)

    优先级: CLI > override YAML > base YAML > 代码默认值
    """

    # 基础配置文件路径
    base_config_path: str = ""
    # 覆盖配置文件路径
    override_config_path: str = ""
    # CLI 参数列表 (None 表示从 sys.argv 解析)
    cli_args: list[str] | None = None
    # 是否允许未知 CLI 参数 (与其他 argparse 结合时需要)
    allow_unknown_args: bool = True
    # 嵌套键分隔符
    key_separator: str = "."


class YAMLConfigManager:
    """YAML 配置管理器

    参考 BasicSR 的 YAML 配置驱动 + CLI 覆盖:
    支持多层级配置合并，CLI 参数可覆盖 YAML 中的任意值。

    Usage:
        manager = YAMLConfigManager(YAMLConfigOptions(
            base_config_path="configs/default.yaml",
            override_config_path="configs/override.yaml",
        ))

        config = manager.load()
        # config = {"model": {"cfg_scale": 3.0, "steps": 20}, ...}

        # CLI 覆盖: --model.cfg_scale 5.0 --model.steps 30
        config = manager.load_with_cli_overrides()
    """

    def __init__(self, options: YAMLConfigOptions | None = None):
        self.options = options or YAMLConfigOptions()
        self._config: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """加载并合并配置

        合并顺序: base YAML -> override YAML -> 代码默认值

        Returns:
            合并后的配置字典
        """
        config: dict[str, Any] = {}

        # 1. 加载基础配置
        if self.options.base_config_path and os.path.exists(self.options.base_config_path):
            base = self._load_yaml(self.options.base_config_path)
            config = self._deep_merge(config, base)
            logger.debug(f"基础配置已加载: {self.options.base_config_path}")

        # 2. 加载覆盖配置
        if self.options.override_config_path and os.path.exists(self.options.override_config_path):
            override = self._load_yaml(self.options.override_config_path)
            config = self._deep_merge(config, override)
            logger.debug(f"覆盖配置已加载: {self.options.override_config_path}")

        self._config = config
        return copy.deepcopy(config)

    def load_with_cli_overrides(self) -> dict[str, Any]:
        """加载配置并应用 CLI 覆盖

        CLI 覆盖格式 (参考 BasicSR):
        --key.subkey value
        例如: --model.cfg_scale 5.0 --model.steps 30

        Returns:
            合并后的配置字典
        """
        config = self.load()

        # 解析 CLI 参数
        cli_overrides = self._parse_cli_overrides()
        if cli_overrides:
            config = self._apply_overrides(config, cli_overrides)
            logger.info(f"CLI 覆盖已应用: {len(cli_overrides)} 项")

        self._config = config
        return copy.deepcopy(config)

    def get(self, key_path: str, default: Any = None) -> Any:
        """获取配置值 (支持嵌套键路径)

        Args:
            key_path: 点分隔的键路径 (e.g., "model.cfg_scale")
            default: 键不存在时的默认值

        Returns:
            配置值
        """
        keys = key_path.split(self.options.key_separator)
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any):
        """设置配置值 (支持嵌套键路径)

        Args:
            key_path: 点分隔的键路径
            value: 要设置的值
        """
        keys = key_path.split(self.options.key_separator)
        config = self._config
        for key in keys[:-1]:
            if key not in config or not isinstance(config[key], dict):
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value

    def save(self, path: str):
        """保存配置到 YAML 文件

        Args:
            path: 目标文件路径
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"配置已保存: {path}")

    def _load_yaml(self, path: str) -> dict[str, Any]:
        """加载 YAML 文件"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典 (override 覆盖 base)"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def _parse_cli_overrides(self) -> dict[str, str]:
        """解析 CLI 覆盖参数

        格式: --key.path value
        以 -- 开头的参数被视为覆盖项，下一个参数为其值。

        Returns:
            键路径到值的映射
        """
        overrides: dict[str, str] = {}

        # 获取参数列表
        args = self.options.cli_args
        if args is None:
            import sys

            args = sys.argv[1:]

        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                key = arg[2:]  # 去掉 "--"
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    overrides[key] = args[i + 1]
                    i += 2
                else:
                    # 布尔标志
                    overrides[key] = "true"
                    i += 1
            else:
                i += 1

        return overrides

    def _apply_overrides(self, config: dict, overrides: dict[str, str]) -> dict:
        """将 CLI 覆盖应用到配置"""
        for key_path, value_str in overrides.items():
            # 尝试推断值的类型
            value = self._infer_type(value_str)
            self._set_nested(config, key_path, value)
            logger.debug(f"CLI 覆盖: {key_path} = {value}")
        return config

    def _set_nested(self, config: dict, key_path: str, value: Any):
        """设置嵌套字典值"""
        keys = key_path.split(self.options.key_separator)
        current = config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    @staticmethod
    def _infer_type(value_str: str) -> Any:
        """推断字符串值的类型"""
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False
        if value_str.lower() == "none":
            return None
        try:
            return int(value_str)
        except ValueError:
            pass
        try:
            return float(value_str)
        except ValueError:
            pass
        return value_str

    @property
    def config(self) -> dict[str, Any]:
        """获取当前配置"""
        return copy.deepcopy(self._config)


# ---------------------------------------------------------------------------
# 2. OmegaConf 配置驱动模型实例化 (DiffBIR P2)
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    """模型配置描述

    参考 DiffBIR 的 OmegaConf + instantiate_from_config 模式:
    使用配置字典描述模型的类路径和初始化参数，
    运行时根据配置动态实例化模型。

    DiffBIR 的配置格式:
    model:
      target: models.ir_model.IRModel
      params:
        inp_size: 512
        encoder: ...
        decoder: ...

    instantiate_from_config(config.model) -> IRModel(inp_size=512, ...)
    """

    # 模型类的完整导入路径
    target: str
    # 模型初始化参数
    params: dict[str, Any] = field(default_factory=dict)
    # 可选的描述信息
    description: str = ""


class ConfigDrivenInstantiator:
    """配置驱动模型实例化

    参考 DiffBIR 的 OmegaConf + instantiate_from_config:
    根据配置字典中的 target 路径和 params 参数，
    动态导入并实例化模型类。

    Usage:
        instantiator = ConfigDrivenInstantiator()

        # 从配置字典实例化
        config = {
            "target": "app.integrated_app.engines.seedvr2_engine.SeedVR2Engine",
            "params": {"model_path": "/path/to/model"},
        }
        model = instantiator.instantiate(config)

        # 从 YAML 配置实例化
        config = yaml_config["model"]
        model = instantiator.instantiate(config)
    """

    # 已解析的类缓存
    _class_cache: dict[str, type] = {}

    def instantiate(self, config: dict[str, Any] | ModelConfig, **extra_params) -> Any:
        """根据配置实例化对象

        参考 DiffBIR 的 instantiate_from_config:
        1. 从 config["target"] 获取类路径
        2. 动态导入该类
        3. 使用 config["params"] 初始化

        Args:
            config: 配置字典或 ModelConfig 对象
            **extra_params: 额外的初始化参数 (覆盖 config.params)

        Returns:
            实例化的对象

        Raises:
            ValueError: 配置中缺少 target
            ImportError: 类路径无法导入
        """
        # 统一为字典
        if isinstance(config, ModelConfig):
            config_dict = {"target": config.target, "params": config.params}
        else:
            config_dict = config

        target = config_dict.get("target")
        if not target:
            raise ValueError("配置中缺少 'target' 字段 (类导入路径)")

        params = config_dict.get("params", {})
        params.update(extra_params)

        # 查找或导入类
        cls = self._resolve_class(target)

        # 实例化
        try:
            instance = cls(**params)
            logger.info(f"配置驱动实例化成功: {target}")
            return instance
        except Exception as e:
            logger.error(f"实例化失败: {target} - {e}")
            raise

    def _resolve_class(self, class_path: str) -> type:
        """解析类路径为类对象

        Args:
            class_path: 完整的类导入路径 (e.g., "module.submodule.ClassName")

        Returns:
            类对象
        """
        # 检查缓存
        if class_path in self._class_cache:
            return self._class_cache[class_path]

        # 拆分模块路径和类名
        parts = class_path.rsplit(".", 1)
        if len(parts) != 2:
            raise ImportError(f"无效的类路径: {class_path}")

        module_path, class_name = parts

        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"无法导入类 {class_path}: {e}") from e

        # 缓存
        self._class_cache[class_path] = cls
        return cls

    def describe_config(self, instance: Any) -> ModelConfig:
        """从实例反向生成配置描述

        Args:
            instance: 要描述的实例

        Returns:
            ModelConfig 描述
        """
        cls = type(instance)
        target = f"{cls.__module__}.{cls.__name__}"

        # 尝试提取初始化参数
        params = {}
        if hasattr(instance, "__init__"):
            import inspect

            sig = inspect.signature(instance.__init__)
            for name, _param in sig.parameters.items():
                if name == "self":
                    continue
                if hasattr(instance, name):
                    value = getattr(instance, name)
                    # 只序列化基本类型
                    if isinstance(value, (int, float, str, bool, type(None))):
                        params[name] = value

        return ModelConfig(target=target, params=params)


# ---------------------------------------------------------------------------
# 3. auto_resume 自动检查点恢复 (BasicSR P2)
# ---------------------------------------------------------------------------


@dataclass
class CheckpointInfo:
    """检查点信息"""

    path: str
    epoch: int = 0
    step: int = 0
    file_size_mb: float = 0.0
    modified_time: float = 0.0


@dataclass
class AutoResumeConfig:
    """自动检查点恢复配置

    参考 BasicSR 的 auto_resume 机制:
    - 启动时自动检测最新的检查点
    - 支持按 epoch/step/时间排序
    - 恢复模型权重 + 优化器状态 + 训练步数
    - 可配置检查点搜索路径和匹配模式

    BasicSR 的 auto_resume 流程:
    1. 在 experiment_dir/models/ 下搜索 checkpoint_*.pth
    2. 按修改时间排序，取最新的
    3. 加载 model_state_dict + training_state
    4. 继续训练或推理
    """

    enabled: bool = True
    # 检查点搜索路径
    search_path: str = ""
    # 检查点文件匹配模式 (glob)
    pattern: str = "*.pth"
    # 排序方式: "time" | "epoch" | "step" | "name"
    sort_by: str = "time"
    # 是否恢复优化器状态 (训练时)
    restore_optimizer: bool = False
    # 是否恢复调度器状态
    restore_scheduler: bool = False
    # 最大保留检查点数量 (0 = 不限制)
    max_keep: int = 5
    # 检查点文件名前缀
    prefix: str = "checkpoint"


class AutoResumeManager:
    """自动检查点恢复管理器

    参考 BasicSR 的 auto_resume 机制:
    在启动时自动检测并恢复最新的检查点，实现断点续训/续推。

    对于 SeedVR2:
    - 推理场景: 恢复模型权重以继续中断的批量任务
    - 不涉及训练优化器恢复

    Usage:
        config = AutoResumeConfig(
            enabled=True,
            search_path="checkpoints/",
            pattern="seedvr2_*.pth",
        )
        manager = AutoResumeManager(config)

        # 查找最新检查点
        latest = manager.find_latest_checkpoint()

        # 恢复模型
        if latest:
            model = manager.resume(model, latest.path)
    """

    def __init__(self, config: AutoResumeConfig | None = None):
        self.config = config or AutoResumeConfig()

    def find_latest_checkpoint(self) -> CheckpointInfo | None:
        """查找最新的检查点

        参考 BasicSR 的搜索流程:
        1. 在搜索路径下匹配文件模式
        2. 按指定方式排序
        3. 返回最新的检查点信息

        Returns:
            CheckpointInfo 或 None (无检查点时)
        """
        if not self.config.enabled:
            logger.debug("auto_resume 已禁用")
            return None

        search_path = self.config.search_path
        if not search_path:
            logger.debug("未配置搜索路径，跳过检查点查找")
            return None

        if not os.path.isdir(search_path):
            logger.debug(f"搜索路径不存在: {search_path}")
            return None

        # 搜索匹配的文件
        import glob

        pattern = os.path.join(search_path, self.config.pattern)
        matches = glob.glob(pattern)

        if not matches:
            logger.debug(f"未找到检查点: {pattern}")
            return None

        # 排序
        checkpoints = [self._parse_checkpoint_info(p) for p in matches]
        checkpoints = [c for c in checkpoints if c is not None]

        if not checkpoints:
            return None

        sort_key = {
            "time": lambda c: c.modified_time,
            "epoch": lambda c: c.epoch,
            "step": lambda c: c.step,
            "name": lambda c: c.path,
        }.get(self.config.sort_by, lambda c: c.modified_time)

        checkpoints.sort(key=sort_key, reverse=True)
        latest = checkpoints[0]

        logger.info(f"找到最新检查点: {os.path.basename(latest.path)} " f"({latest.file_size_mb:.1f}MB)")
        return latest

    def resume(self, model: torch.nn.Module, checkpoint_path: str) -> torch.nn.Module:
        """从检查点恢复模型

        参考 BasicSR 的恢复流程:
        1. 加载 checkpoint 文件
        2. 提取 model_state_dict
        3. 加载到模型

        Args:
            model: 目标模型
            checkpoint_path: 检查点文件路径

        Returns:
            恢复后的模型
        """
        if not os.path.exists(checkpoint_path):
            logger.error(f"检查点不存在: {checkpoint_path}")
            return model

        logger.info(f"从检查点恢复: {checkpoint_path}")

        try:
            checkpoint = _safe_torch_load(
                checkpoint_path,
                map_location="cpu",
                allow_pickle_fallback=True,
                purpose="checkpoint-resume",
            )

            # 提取 state_dict
            if isinstance(checkpoint, dict):
                state_dict = checkpoint.get("state_dict", checkpoint.get("model_state_dict", checkpoint))
            else:
                state_dict = checkpoint

            # 加载到模型
            missing, unexpected = model.load_state_dict(state_dict, strict=False)

            if missing:
                logger.warning(f"缺失的键: {len(missing)} 个")
            if unexpected:
                logger.warning(f"意外的键: {len(unexpected)} 个")

            logger.info("检查点恢复成功")

        except Exception as e:
            logger.error(f"检查点恢复失败: {e}")

        return model

    def save_checkpoint(
        self,
        model: torch.nn.Module,
        save_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """保存检查点

        Args:
            model: 模型
            save_path: 保存路径
            metadata: 额外的元数据

        Returns:
            是否保存成功
        """
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        checkpoint = {
            "state_dict": model.state_dict(),
            "timestamp": time.time(),
        }
        if metadata:
            checkpoint["metadata"] = metadata

        try:
            torch.save(checkpoint, save_path)  # nosemgrep: pickles-in-pytorch - torch.save 为序列化（非反序列化），非 RCE 向量
            logger.info(f"检查点已保存: {save_path}")
            return True
        except Exception as e:
            logger.error(f"检查点保存失败: {e}")
            return False

    def cleanup_old_checkpoints(self) -> int:
        """清理旧检查点 (保留最新 max_keep 个)

        Returns:
            删除的检查点数量
        """
        if self.config.max_keep <= 0:
            return 0

        import glob

        pattern = os.path.join(self.config.search_path, self.config.pattern)
        matches = glob.glob(pattern)

        if len(matches) <= self.config.max_keep:
            return 0

        # 按时间排序
        matches.sort(key=os.path.getmtime, reverse=True)
        to_delete = matches[self.config.max_keep :]

        deleted = 0
        for path in to_delete:
            try:
                os.remove(path)
                deleted += 1
                logger.debug(f"已删除旧检查点: {path}")
            except OSError as e:
                logger.warning(f"删除检查点失败: {path} - {e}")

        logger.info(f"已清理 {deleted} 个旧检查点")
        return deleted

    def _parse_checkpoint_info(self, path: str) -> CheckpointInfo | None:
        """解析检查点文件信息"""
        try:
            stat = os.stat(path)
            name = os.path.basename(path)

            # 尝试从文件名解析 epoch/step
            epoch = 0
            step = 0
            # 格式: checkpoint_epoch100_step5000.pth
            import re

            epoch_match = re.search(r"epoch(\d+)", name)
            step_match = re.search(r"step(\d+)", name)
            if epoch_match:
                epoch = int(epoch_match.group(1))
            if step_match:
                step = int(step_match.group(1))

            return CheckpointInfo(
                path=path,
                epoch=epoch,
                step=step,
                file_size_mb=stat.st_size / (1024 * 1024),
                modified_time=stat.st_mtime,
            )
        except OSError:
            return None


# ---------------------------------------------------------------------------
# 4. 多 GPU 并行推理 (CogVideo P3)
# ---------------------------------------------------------------------------


class ParallelStrategy(StrEnum):
    """多 GPU 并行策略

    参考 CogVideo 的 xDiT xFuser 集成:
    - ULYSSES: 将注意力头分配到不同 GPU (序列并行)
    - RING: 将序列维度分配到不同 GPU (环形注意力)
    - PIPELINE: 将模型层分配到不同 GPU (流水线并行)
    - DATA: 不同 GPU 处理不同数据 (数据并行)
    """

    ULYSSES = "ulysses"
    RING = "ring"
    PIPELINE = "pipeline"
    DATA = "data"


@dataclass
class MultiGPUConfig:
    """多 GPU 并行配置

    参考 CogVideo 使用 xDiT xFuser 的多 GPU 推理:
    - Ulysses Attention: 注意力头在 GPU 间分配
    - Ring Attention: 序列长度在 GPU 间分配
    - 两者可组合使用 (2D 并行)

    CogVideo 的集成:
    - from xfuser import xFuserArgs
    - engine_args = xFuserArgs(model_args)
    - engine = xFuserEngine(engine_args)
    - output = engine.generate(...)
    """

    enabled: bool = False
    # 并行策略
    strategy: ParallelStrategy = ParallelStrategy.ULYSSES
    # 可见的 GPU 设备 ID
    gpu_ids: list[int] = field(default_factory=lambda: [0])
    # Ulysses 并行度 (注意力头分配数)
    ulysses_degree: int = 1
    # Ring 并行度 (序列分配数)
    ring_degree: int = 1
    # 通信后端: "nccl" | "gloo"
    backend: str = "nccl"


class MultiGPUInference:
    """多 GPU 并行推理框架

    参考 CogVideo 的 xDiT xFuser Ulysses/Ring Attention:
    将 DiT 模型分布到多个 GPU 上并行推理。

    约束:
    - 需要多张 NVIDIA GPU
    - GPU 间通信需要 NCCL 后端
    - 模型必须支持注意力头分割

    注意: 此模块为参考框架，实际多 GPU 推理需要:
    1. 安装 xdiT/xfuser 库
    2. 初始化进程组
    3. 对模型应用并行策略

    Usage:
        config = MultiGPUConfig(
            enabled=True,
            strategy=ParallelStrategy.ULYSSES,
            gpu_ids=[0, 1],
            ulysses_degree=2,
        )
        inference = MultiGPUInference(config)

        if inference.is_available():
            model = inference.setup(model)
    """

    def __init__(self, config: MultiGPUConfig | None = None):
        self.config = config or MultiGPUConfig()
        self._setup_done: bool = False

    def is_available(self) -> bool:
        """检测多 GPU 推理是否可用"""
        if not torch.cuda.is_available():
            return False
        num_gpus = torch.cuda.device_count()
        return num_gpus >= 2

    def get_gpu_count(self) -> int:
        """获取可用 GPU 数量"""
        return torch.cuda.device_count() if torch.cuda.is_available() else 0

    def get_gpu_info(self) -> list[dict[str, Any]]:
        """获取所有 GPU 信息"""
        info = []
        if not torch.cuda.is_available():
            return info

        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            info.append(
                {
                    "id": i,
                    "name": props.name,
                    "total_memory_gb": props.total_memory / (1024**3),
                    "major": props.major,
                    "minor": props.minor,
                }
            )
        return info

    def setup(self, model: torch.nn.Module) -> torch.nn.Module:
        """设置多 GPU 并行

        参考 CogVideo 的 xDiT 集成流程:
        1. 检查 GPU 可用性
        2. 初始化进程组
        3. 应用并行策略到模型

        Args:
            model: 要并行化的模型

        Returns:
            并行化后的模型
        """
        if not self.config.enabled:
            logger.debug("多 GPU 推理已禁用")
            return model

        if not self.is_available():
            logger.warning("多 GPU 推理不可用 (需要 2+ GPU)")
            return model

        gpu_count = self.get_gpu_count()
        required = len(self.config.gpu_ids)
        if gpu_count < required:
            logger.warning(f"GPU 数量不足: 需要 {required}, 可用 {gpu_count}")
            return model

        logger.info(f"多 GPU 并行配置: strategy={self.config.strategy.value}, " f"gpu_ids={self.config.gpu_ids}")

        # 参考流程 (框架代码)
        if self.config.strategy == ParallelStrategy.ULYSSES:
            self._setup_ulysses(model)
        elif self.config.strategy == ParallelStrategy.RING:
            self._setup_ring(model)
        elif self.config.strategy == ParallelStrategy.PIPELINE:
            self._setup_pipeline(model)
        elif self.config.strategy == ParallelStrategy.DATA:
            self._setup_data_parallel(model)

        self._setup_done = True
        return model

    def _setup_ulysses(self, model: torch.nn.Module):
        """设置 Ulysses 注意力并行

        参考 xDiT 的 Ulysses 策略:
        - 将注意力头均匀分配到各 GPU
        - 每个 GPU 计算部分注意力头
        - 通过 All-Gather 合并结果

        需要: xdiT 库
        """
        logger.info(
            f"Ulysses 并行: degree={self.config.ulysses_degree}, "
            f"将注意力头分配到 {self.config.ulysses_degree} 个 GPU"
        )
        logger.warning("Ulysses 并行为参考框架，实际使用需安装 xdiT 库")

    def _setup_ring(self, model: torch.nn.Module):
        """设置 Ring Attention 并行

        参考 xDiT 的 Ring 策略:
        - 将序列长度分配到各 GPU
        - 环形通信实现全局注意力
        - 支持超长序列推理

        需要: xdiT 库
        """
        logger.info(f"Ring 并行: degree={self.config.ring_degree}, " f"将序列分配到 {self.config.ring_degree} 个 GPU")
        logger.warning("Ring 并行为参考框架，实际使用需安装 xdiT 库")

    def _setup_pipeline(self, model: torch.nn.Module):
        """设置流水线并行

        将模型的不同层分配到不同 GPU:
        - GPU 0: 浅层 block
        - GPU 1: 深层 block
        - 微批次流水线提高利用率
        """
        if not hasattr(model, "blocks"):
            logger.warning("模型无 blocks 属性，无法流水线并行")
            return

        num_blocks = len(model.blocks)
        num_gpus = len(self.config.gpu_ids)
        blocks_per_gpu = num_blocks // num_gpus

        logger.info(f"流水线并行: {num_blocks} blocks 分配到 {num_gpus} 个 GPU, " f"约 {blocks_per_gpu} blocks/GPU")
        logger.warning("流水线并行为参考框架，实际使用需实现层间通信")

    def _setup_data_parallel(self, model: torch.nn.Module):
        """设置数据并行

        不同 GPU 处理不同输入数据。
        使用 torch.nn.DataParallel 或 DistributedDataParallel。
        """
        device_ids = self.config.gpu_ids
        model = torch.nn.DataParallel(model, device_ids=device_ids)
        logger.info(f"数据并行已设置: {len(device_ids)} 个 GPU")

    @property
    def is_setup(self) -> bool:
        """是否已完成设置"""
        return self._setup_done


# ---------------------------------------------------------------------------
# 5. CPU/CUDA Prefetcher (BasicSR P2)
# ---------------------------------------------------------------------------


@dataclass
class PrefetcherConfig:
    """数据预取配置

    参考 BasicSR 的 CPU/CUDA Prefetcher:
    - 在 GPU 计算当前批次时，CPU 预取下一批次数据
    - 实现 CPU-GPU 流水线并行
    - 减少 GPU 等待 CPU 数据准备的时间

    BasicSR 的实现:
    - CPUPrefetcher: 在 CPU 上预取和预处理数据
    - CUDAPrefetcher: 将预取数据提前传输到 GPU
    - 通过迭代器接口与训练/推理循环集成
    """

    enabled: bool = False
    # 预取队列大小 (预取几个批次)
    prefetch_count: int = 2
    # 是否使用 CUDA 预取 (将数据提前搬到 GPU)
    cuda_prefetch: bool = True
    # 目标 CUDA 设备
    device: str = "cuda:0"


class CUDAPrefetcher:
    """CUDA 数据预取器

    参考 BasicSR 的 CUDAPrefetcher 实现:
    在后台线程中将数据从 CPU 传输到 GPU，
    与当前 GPU 计算并行，减少数据传输等待时间。

    工作原理:
    1. 主线程: GPU 计算当前批次
    2. 后台线程: 将下一批次数据传输到 GPU (cuda.mem_map 或 pin_memory)
    3. 主线程取下一批次时，数据已在 GPU 上

    Usage:
        # 创建预取器
        prefetcher = CUDAPrefetcher(data_loader, device="cuda:0")

        # 迭代数据
        for batch in prefetcher:
            # batch 已在 GPU 上，GPU 计算同时后台预取下一批次
            output = model(batch)
    """

    def __init__(
        self,
        data_loader: Any,
        device: str | torch.device = "cuda:0",
        prefetch_count: int = 2,
    ):
        """初始化 CUDA 预取器

        Args:
            data_loader: 数据加载器 (可迭代对象)
            device: 目标 CUDA 设备
            prefetch_count: 预取队列大小
        """
        self.data_loader = data_loader
        self.device = torch.device(device) if isinstance(device, str) else device
        self.prefetch_count = prefetch_count

        self._stream = torch.cuda.Stream(device=self.device) if torch.cuda.is_available() else None
        self._preload_queue: list[Any] = []
        self._iterator = iter(data_loader)

    def __iter__(self):
        """开始迭代"""
        self._iterator = iter(self.data_loader)
        self._preload_queue.clear()

        # 预取前几个批次
        for _ in range(self.prefetch_count):
            self._preload_next()

        return self

    def __next__(self) -> Any:
        """获取下一个批次 (已在 GPU 上)"""
        if not self._preload_queue:
            raise StopIteration

        # 取出已预取的批次
        batch = self._preload_queue.pop(0)

        # 预取下一批次
        self._preload_next()

        return batch

    def _preload_next(self):
        """预取下一批次到 GPU"""
        try:
            batch = next(self._iterator)
        except StopIteration:
            return

        if self._stream is not None:
            with torch.cuda.stream(self._stream):
                batch = self._to_device(batch)
        else:
            batch = self._to_device(batch)

        self._preload_queue.append(batch)

    def _to_device(self, data: Any) -> Any:
        """将数据传输到 GPU

        支持: Tensor, dict, list, tuple
        """
        if isinstance(data, torch.Tensor):
            return data.to(self.device, non_blocking=True)
        elif isinstance(data, dict):
            return {k: self._to_device(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return type(data)(self._to_device(item) for item in data)
        else:
            return data


class CPUPrefetcher:
    """CPU 数据预取器

    参考 BasicSR 的 CPUPrefetcher:
    在后台线程中预取和预处理下一批次数据，
    减少 GPU 等待 CPU 数据准备的时间。

    与 CUDAPrefetcher 的区别:
    - CPUPrefetcher: 数据留在 CPU 上 (适合 CPU 预处理场景)
    - CUDAPrefetcher: 数据预传输到 GPU (适合数据已在 GPU 的场景)

    Usage:
        prefetcher = CPUPrefetcher(data_loader, prefetch_count=2)
        for batch in prefetcher:
            # batch 在 CPU 上，由主线程负责传到 GPU
            batch = batch.to("cuda:0")
            output = model(batch)
    """

    def __init__(self, data_loader: Any, prefetch_count: int = 2):
        self.data_loader = data_loader
        self.prefetch_count = prefetch_count
        self._preload_queue: list[Any] = []
        self._iterator = iter(data_loader)

    def __iter__(self):
        self._iterator = iter(self.data_loader)
        self._preload_queue.clear()

        # 预取
        for _ in range(self.prefetch_count):
            self._preload_next()

        return self

    def __next__(self) -> Any:
        if not self._preload_queue:
            raise StopIteration

        batch = self._preload_queue.pop(0)
        self._preload_next()
        return batch

    def _preload_next(self):
        try:
            batch = next(self._iterator)
            self._preload_queue.append(batch)
        except StopIteration:
            pass


# ---------------------------------------------------------------------------
# 6. 模型自描述属性 (waifu2x P2)
# ---------------------------------------------------------------------------


@dataclass
class ModelMetadata:
    """模型自描述元数据

    参考 waifu2x 的 w2nn* 属性模式:
    在模型文件中嵌入自描述属性，推理时自动读取并适配。

    waifu2x 的 w2nn 属性:
    - w2nn_model_arch: 模型架构标识 (e.g., "upconv_7", "vgg_7")
    - w2nn_offset: 输出偏移量
    - w2nn_scale: 放大倍率
    - w2nn_channels: 通道数

    推理时的自动适配:
    1. 加载模型时检查 w2nn 属性
    2. 根据 arch 选择对应的推理路径
    3. 根据 scale/channels 自动配置前后处理
    """

    # 模型架构标识
    architecture: str = ""
    # 模型版本
    version: str = ""
    # 支持的放大倍率
    scale_factor: float = 1.0
    # 输入通道数
    input_channels: int = 3
    # 输出通道数
    output_channels: int = 3
    # 输入偏移 (waifu2x offset 概念)
    offset: int = 0
    # 最大输入分辨率 (0 = 无限制)
    max_input_resolution: int = 0
    # 模型描述
    description: str = ""
    # 自定义扩展属性
    extra: dict[str, Any] = field(default_factory=dict)

    # 属性前缀 (参考 waifu2x 的 w2nn 命名)
    ATTRIBUTE_PREFIX = "seedvr2_"

    def to_state_dict_extras(self) -> dict[str, Any]:
        """将元数据导出为 state_dict 附加项

        在保存模型时，将元数据作为顶层键嵌入 state_dict:
        {
            "seedvr2_architecture": "dit",
            "seedvr2_version": "1.0",
            "seedvr2_scale_factor": 1.0,
            ...
        }
        """
        extras = {}
        prefix = self.ATTRIBUTE_PREFIX

        extras[f"{prefix}architecture"] = self.architecture
        extras[f"{prefix}version"] = self.version
        extras[f"{prefix}scale_factor"] = self.scale_factor
        extras[f"{prefix}input_channels"] = self.input_channels
        extras[f"{prefix}output_channels"] = self.output_channels
        extras[f"{prefix}offset"] = self.offset
        extras[f"{prefix}max_input_resolution"] = self.max_input_resolution
        extras[f"{prefix}description"] = self.description

        for key, value in self.extra.items():
            extras[f"{prefix}{key}"] = value

        return extras

    @classmethod
    def from_state_dict(cls, state_dict: dict[str, Any]) -> "ModelMetadata":
        """从 state_dict 中提取元数据

        Args:
            state_dict: 模型的 state_dict

        Returns:
            ModelMetadata 实例
        """
        prefix = cls.ATTRIBUTE_PREFIX
        metadata = cls()

        for key, value in state_dict.items():
            if key.startswith(prefix):
                attr_name = key[len(prefix) :]
                if hasattr(metadata, attr_name):
                    try:
                        setattr(metadata, attr_name, value)
                    except (TypeError, AttributeError):
                        metadata.extra[attr_name] = value
                else:
                    metadata.extra[attr_name] = value

        return metadata


class ModelSelfDescriptor:
    """模型自描述管理器

    参考 waifu2x 的 w2nn* 模式:
    在模型保存时嵌入自描述属性，加载时自动读取并适配。

    Usage:
        descriptor = ModelSelfDescriptor()

        # 保存时嵌入元数据
        metadata = ModelMetadata(
            architecture="dit",
            version="1.0",
            scale_factor=1.0,
            input_channels=3,
        )
        descriptor.save_with_metadata(model, metadata, "model.pth")

        # 加载时自动读取
        model, metadata = descriptor.load_with_metadata(model, "model.pth")

        # 根据 metadata 自动适配
        if metadata.architecture == "dit":
            # 使用 DiT 推理路径
            pass
    """

    def save_with_metadata(
        self,
        model: torch.nn.Module,
        metadata: ModelMetadata,
        path: str,
    ) -> bool:
        """保存模型并嵌入自描述元数据

        Args:
            model: 要保存的模型
            metadata: 模型元数据
            path: 保存路径

        Returns:
            是否保存成功
        """
        try:
            state_dict = model.state_dict()
            extras = metadata.to_state_dict_extras()
            state_dict.update(extras)

            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            torch.save(state_dict, path)

            logger.info(f"模型已保存 (含 {len(extras)} 项自描述属性): {path}")
            return True

        except Exception as e:
            logger.error(f"模型保存失败: {e}")
            return False

    def load_with_metadata(
        self,
        model: torch.nn.Module,
        path: str,
        strict: bool = False,
    ) -> tuple[torch.nn.Module, ModelMetadata | None]:
        """加载模型并提取自描述元数据

        Args:
            model: 目标模型
            path: 检查点路径
            strict: 是否严格匹配 state_dict 键

        Returns:
            (模型, 元数据) 元组
        """
        try:
            state_dict = _safe_torch_load(
                path,
                map_location="cpu",
                allow_pickle_fallback=True,
                purpose="model-self-descriptor-metadata",
            )

            # 提取元数据
            metadata = ModelMetadata.from_state_dict(state_dict)

            # 从 state_dict 中移除元数据键，避免加载到模型参数
            prefix = ModelMetadata.ATTRIBUTE_PREFIX
            clean_state_dict = {k: v for k, v in state_dict.items() if not k.startswith(prefix)}

            # 加载模型权重
            missing, unexpected = model.load_state_dict(clean_state_dict, strict=strict)

            if metadata.architecture:
                logger.info(
                    f"模型自描述: arch={metadata.architecture}, "
                    f"version={metadata.version}, "
                    f"scale={metadata.scale_factor}"
                )

            return model, metadata

        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            return model, None

    def inspect_metadata(self, path: str) -> ModelMetadata | None:
        """检查模型文件的元数据 (不加载模型权重)

        Args:
            path: 模型文件路径

        Returns:
            ModelMetadata 或 None
        """
        try:
            state_dict = _safe_torch_load(
                path,
                map_location="cpu",
                allow_pickle_fallback=True,
                purpose="metadata-inspection",
            )
            return ModelMetadata.from_state_dict(state_dict)
        except Exception as e:
            logger.error(f"元数据检查失败: {e}")
            return None


# ---------------------------------------------------------------------------
# 7. pybind11 零拷贝调用 (Anime4KCPP P2)
# ---------------------------------------------------------------------------


@dataclass
class PyBindConfig:
    """pybind11 零拷贝配置

    参考 Anime4KCPP 的 pybind11 集成:
    - C++ 引擎通过 pybind11 暴露 Python 接口
    - NumPy 数组零拷贝传递 (避免 CPU-GPU 间数据复制)
    - 支持 CPU 和 GPU 后端

    Anime4KCPP 的绑定设计:
    - ACNet 参数直接传 numpy.ndarray
    - 内部使用 py::array_t<float, py::array::c_style | py::array::forcecast>
    - 返回也是 numpy 数组 (零拷贝)
    """

    enabled: bool = False
    # C++ 扩展模块名
    module_name: str = "seedvr2_cpp"
    # 是否启用 GPU 后端
    gpu_backend: bool = True
    # CUDA 设备 ID
    device_id: int = 0
    # 是否使用零拷贝 (避免内存拷贝)
    zero_copy: bool = True


class PyBindInterface:
    """pybind11 零拷贝调用接口

     参考 Anime4KCPP 的 pybind11 集成模式:
     通过 pybind11 将 C++ 推理引擎暴露为 Python 接口，
     支持 NumPy 数组的零拷贝传递。

     零拷贝原理:
     1. Python 端传入 numpy.ndarray (连续内存)
     2. pybind11 直接获取底层指针 (不复制)
     3. C++ 处理后返回新的 numpy 数组 (也不复制)

    Anime4KCPP 的典型绑定:

     C++ 侧:
         py::array_t<float> process(py::array_t<float, py::array::c_style> input) {
             auto buf = input.request();
             float* ptr = static_cast<float*>(buf.ptr);
             // 直接操作 ptr，零拷贝
             ...
             return py::array_t<float>(...);
         }

     Python 侧:
         import seedvr2_cpp
         output = seedvr2_cpp.process(input_array)  # 零拷贝

     注意: 此模块为参考框架，实际 C++ 绑定需要编译扩展模块。

     Usage:
         interface = PyBindInterface(PyBindConfig(enabled=True))

         if interface.is_available():
             result = interface.call("process", input_array)
    """

    def __init__(self, config: PyBindConfig | None = None):
        self.config = config or PyBindConfig()
        self._module = None

    def is_available(self) -> bool:
        """检测 C++ 扩展模块是否可用"""
        try:
            __import__(self.config.module_name)
            return True
        except ImportError:
            return False

    def load_module(self) -> Any:
        """加载 C++ 扩展模块

        Returns:
            模块对象

        Raises:
            ImportError: 模块不可用
        """
        if self._module is not None:
            return self._module

        try:
            self._module = __import__(self.config.module_name)
            logger.info(f"C++ 扩展已加载: {self.config.module_name}")
            return self._module
        except ImportError as e:
            logger.error(f"C++ 扩展不可用: {self.config.module_name} - {e}")
            raise

    def call(self, func_name: str, *args, **kwargs) -> Any:
        """调用 C++ 扩展函数

        Args:
            func_name: 函数名
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值
        """
        module = self.load_module()
        func = getattr(module, func_name, None)

        if func is None:
            raise AttributeError(f"C++ 扩展 {self.config.module_name} 中无函数 {func_name}")

        return func(*args, **kwargs)

    def numpy_to_tensor(self, array: Any, device: str = "cuda:0") -> torch.Tensor:
        """将 NumPy 数组零拷贝转换为 PyTorch Tensor

        参考 Anime4KCPP 的零拷贝策略:
        使用 torch.from_numpy 实现 CPU 端零拷贝，
        然后 non_blocking 传输到 GPU。

        Args:
            array: NumPy ndarray
            device: 目标设备

        Returns:
            PyTorch Tensor
        """
        import numpy as np

        if isinstance(array, np.ndarray):
            # torch.from_numpy 零拷贝 (共享底层内存)
            tensor = torch.from_numpy(array)
            if device.startswith("cuda"):
                tensor = tensor.to(device, non_blocking=True)
            return tensor
        else:
            return torch.as_tensor(array, device=device)

    def tensor_to_numpy(self, tensor: torch.Tensor) -> Any:
        """将 PyTorch Tensor 转换为 NumPy 数组

        如果 Tensor 在 GPU 上，先拷贝到 CPU 再转换。

        Args:
            tensor: PyTorch Tensor

        Returns:
            NumPy ndarray
        """
        if tensor.is_cuda:
            tensor = tensor.cpu()
        return tensor.numpy()


# ---------------------------------------------------------------------------
# 8. Hydra 配置管理 (Fast-SRGAN P3)
# ---------------------------------------------------------------------------


@dataclass
class HydraConfig:
    """Hydra 配置管理选项

    参考 Fast-SRGAN 的 Hydra 集成:
    - YAML 配置文件定义所有参数
    - CLI 覆盖支持 (key=value 格式)
    - 配置组 (config groups) 和默认组合
    - 多运行 (multirun) 扫描参数空间

    Hydra 的核心概念:
    - config_path: 配置文件目录
    - config_name: 主配置文件名
    - overrides: CLI 覆盖参数

    与 BasicSR YAML 配置的区别:
    - BasicSR: 手写 YAML 解析 + CLI
    - Hydra: 框架级配置管理，支持组合和多运行
    """

    # 配置文件目录
    config_path: str = "configs"
    # 主配置文件名 (不含 .yaml)
    config_name: str = "config"
    # CLI 覆盖参数
    overrides: list[str] = field(default_factory=list)
    # 是否使用 Hydra 的多运行模式
    multirun: bool = False
    # 多运行参数 (参数扫描范围)
    sweep_params: dict[str, list[Any]] = field(default_factory=dict)


class HydraStyleConfigManager:
    """Hydra 风格配置管理器

    参考 Fast-SRGAN 的 Hydra 配置管理:
    提供类似 Hydra 的配置管理能力，但不引入 Hydra 依赖。

    支持特性:
    - YAML 配置文件加载
    - CLI key=value 覆盖
    - 配置组合 (base + override)
    - 参数验证

    注意: 此为 Hydra 风格的轻量实现。
    完整的 Hydra 功能 (multirun, config groups, instantiate)
    请直接使用 hydra-core 包。

    Usage:
        manager = HydraStyleConfigManager(HydraConfig(
            config_path="configs",
            config_name="default",
            overrides=["model.cfg_scale=5.0", "model.steps=30"],
        ))

        config = manager.load()
    """

    def __init__(self, config: HydraConfig | None = None):
        self.config = config or HydraConfig()
        self._yaml_config = YAMLConfigManager()

    def load(self) -> dict[str, Any]:
        """加载并合并配置

        流程:
        1. 加载主配置文件
        2. 应用 CLI 覆盖 (key=value 格式)
        3. 返回合并后的配置

        Returns:
            合并后的配置字典
        """
        # 加载主配置
        main_config_path = os.path.join(
            self.config.config_path,
            f"{self.config.config_name}.yaml",
        )

        config: dict[str, Any] = {}
        if os.path.exists(main_config_path):
            config = self._yaml_config._load_yaml(main_config_path)
            logger.debug(f"主配置已加载: {main_config_path}")

        # 应用覆盖
        for override in self.config.overrides:
            config = self._apply_override(config, override)

        if self.config.overrides:
            logger.info(f"已应用 {len(self.config.overrides)} 项覆盖")

        return config

    def _apply_override(self, config: dict, override: str) -> dict:
        """应用单条覆盖 (key=value 格式)

        Hydra 的覆盖格式:
        - key=value: 设置值
        - key=null: 设置为 None
        - key=[1,2,3]: 设置为列表
        - +key=value: 添加新键
        - ~key: 删除键

        Args:
            config: 当前配置
            override: 覆盖字符串

        Returns:
            更新后的配置
        """
        # 解析覆盖
        add_new = override.startswith("+")
        delete = override.startswith("~")

        if add_new:
            override = override[1:]
        if delete:
            override = override[1:]

        if "=" in override:
            key_path, value_str = override.split("=", 1)
            value = self._parse_override_value(value_str)

            if delete:
                self._delete_nested(config, key_path)
            else:
                self._yaml_config._set_nested(config, key_path, value)
                logger.debug(f"覆盖: {key_path} = {value}")
        elif delete:
            self._delete_nested(config, override)

        return config

    def _parse_override_value(self, value_str: str) -> Any:
        """解析覆盖值"""
        if value_str == "null":
            return None
        if value_str == "true":
            return True
        if value_str == "false":
            return False
        # 列表格式: [1,2,3]
        if value_str.startswith("[") and value_str.endswith("]"):
            try:
                import ast

                return ast.literal_eval(value_str)
            except (ValueError, SyntaxError):
                pass
        # 尝试数值
        try:
            return int(value_str)
        except ValueError:
            pass
        try:
            return float(value_str)
        except ValueError:
            pass
        return value_str

    def _delete_nested(self, config: dict, key_path: str):
        """删除嵌套键"""
        keys = key_path.split(".")
        current = config
        for key in keys[:-1]:
            if key in current and isinstance(current[key], dict):
                current = current[key]
            else:
                return
        current.pop(keys[-1], None)

    def generate_multirun_configs(self) -> list[dict[str, Any]]:
        """生成多运行配置 (参数扫描)

        参考 Hydra 的 multirun 模式:
        对 sweep_params 中的参数进行笛卡尔积扫描，
        生成多个配置实例。

        Returns:
            配置字典列表
        """
        if not self.config.sweep_params:
            return [self.load()]

        import itertools

        # 构建参数组合
        keys = list(self.config.sweep_params.keys())
        values = list(self.config.sweep_params.values())
        combinations = list(itertools.product(*values))

        configs = []
        for combo in combinations:
            config = self.load()
            for key, value in zip(keys, combo, strict=False):
                self._yaml_config._set_nested(config, key, value)
            configs.append(config)

        logger.info(f"多运行: {len(configs)} 个配置组合")
        return configs


# ---------------------------------------------------------------------------
# 便捷工厂函数
# ---------------------------------------------------------------------------


def create_default_config_manager(
    config_path: str = "config.yaml",
) -> YAMLConfigManager:
    """创建默认 YAML 配置管理器"""
    return YAMLConfigManager(YAMLConfigOptions(base_config_path=config_path))


def create_auto_resume_manager(
    search_path: str = "checkpoints/",
    pattern: str = "*.pth",
) -> AutoResumeManager:
    """创建自动检查点恢复管理器"""
    return AutoResumeManager(
        AutoResumeConfig(
            search_path=search_path,
            pattern=pattern,
        )
    )


def create_model_descriptor() -> ModelSelfDescriptor:
    """创建模型自描述管理器"""
    return ModelSelfDescriptor()
