#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""
SeedVR2 - 配置加载模块

所属项目：SeedVR2 (AI-powered video & image super-resolution toolkit)
核心功能：
    - YAML 配置文件加载与解析
    - Pydantic 模型验证（类型检查、范围校验、未知字段过滤）
    - 验证失败回退机制，保证启动不被配置错误阻塞
    - 配置原子写入，避免半写状态损坏配置文件
    - 提供向后兼容的字典接口和类型安全的模型接口

核心技术栈：
    - PyYAML 用于 YAML 文件解析与序列化
    - Pydantic 用于配置数据验证和类型强制
    - tempfile + os.replace 实现原子写入
    - contextlib.suppress 安全清理临时文件
"""

import contextlib
import logging
import os
import tempfile

import yaml

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """加载项目根目录下的 .env 文件（无第三方依赖，纯标准库实现）。

    解析简单的 KEY=VALUE 行，忽略 # 注释和空行。
    使用 os.environ.setdefault 写入，保证显式系统环境变量优先级高于 .env 文件。
    支持去除首尾单引号/双引号，以及将字面量 \\n 转换为真实换行（多行 PEM 密钥等场景）。

    .env 文件路径为项目根目录下的 .env（与 config.yaml 同级）。
    文件不存在时静默返回，不影响应用启动。
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(project_root, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # 去除首尾引号（单引号或双引号）
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                # 将字面量 \n 转换为真实换行（多行 PEM 密钥等场景）
                value = value.replace("\\n", "\n")
                if key:
                    os.environ.setdefault(key, value)
    except Exception as e:
        logger.warning(f".env 文件加载失败: {e}")


def load_config(config_path: str | None = None) -> dict:
    """加载配置文件并返回原始字典格式（向后兼容接口）。

    内部调用 load_validated_config 进行 Pydantic 验证，确保配置值的
    类型和范围正确，并自动过滤未知字段。验证失败时回退到原始 YAML 加载，
    保证应用不会因配置文件格式问题而无法启动。

    Args:
        config_path: 配置文件路径，为 None 时默认使用项目根目录的 config.yaml。

    Returns:
        dict: 配置字典，键为配置节名称（如 'server'、'model'），值为对应配置字典。
              配置文件不存在时返回空字典 {}。

    Note:
        - 优先返回验证后的配置（model_dump 序列化）
        - 验证失败时静默回退到原始 yaml.safe_load
        - 此接口保持向后兼容，新代码建议使用 get_app_config() 获取类型安全的 AppConfig 实例
    """
    _load_dotenv()
    try:
        validated = load_validated_config(config_path)
        return validated.model_dump()
    except Exception:
        if config_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(project_root, "config.yaml")

        if not os.path.exists(config_path):
            return {}

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


def load_validated_config(config_path: str | None = None):
    """加载并通过 Pydantic 模型验证配置文件。

    使用 AppConfig 模型对配置进行严格验证，包括：
    - 自动类型转换（如端口号字符串转整数）
    - 字段范围校验（如端口 1-65535、重试次数 0-10）
    - extra="ignore" 自动过滤 config.yaml 中的未知字段
    - 默认值填充（缺失字段使用模型定义的默认值）

    Args:
        config_path: 配置文件路径，为 None 时默认使用项目根目录的 config.yaml。

    Returns:
        AppConfig: 验证后的配置模型实例，可通过属性访问（如 config.server.port）。
                   配置文件不存在时返回默认配置的 AppConfig 实例。

    Raises:
        pydantic.ValidationError: 配置字段值不合法且无法自动转换时抛出
                                 （但 load_config 会捕获此异常并回退）。
        FileNotFoundError: 指定路径的配置文件不存在时抛出
                          （但有默认路径存在性检查，通常不会触发）。
    """
    from .config_models import AppConfig

    _load_dotenv()
    if config_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.yaml")

    if not os.path.exists(config_path):
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(**raw)


def get_app_config(config_path: str | None = None):
    """获取验证后的 AppConfig 实例（类型安全接口）。

    这是推荐的新代码使用接口，返回带类型提示的 Pydantic 模型实例，
    支持 IDE 自动补全和类型检查。

    Args:
        config_path: 配置文件路径，为 None 时默认使用项目根目录的 config.yaml。

    Returns:
        AppConfig: 验证后的配置模型实例。

    Example:
        >>> config = get_app_config()
        >>> port = config.server.port
        >>> log_level = config.logging.level
    """
    return load_validated_config(config_path)


def save_config(config: dict, config_path: str | None = None) -> None:
    """原子写入保存配置到 YAML 文件。

    使用临时文件 + 原子替换策略避免写入过程中断导致配置文件损坏：
    1. 在目标目录创建隐藏临时文件（.config_*.tmp）
    2. 写入配置内容到临时文件
    3. 使用 os.replace 原子替换目标文件（同文件系统内是原子操作）
    4. 失败时安全清理临时文件

    Args:
        config: 要保存的配置字典。
        config_path: 目标配置文件路径，为 None 时默认保存到项目根目录的 config.yaml。

    Raises:
        OSError: 目录创建、文件写入或替换失败时抛出（临时文件会被自动清理）。
        yaml.YAMLError: YAML 序列化失败时抛出。

    Note:
        - default_flow_style=False 生成易读的块风格 YAML
        - allow_unicode=True 正确保存中文等非 ASCII 字符
        - 自动创建目标目录（如果不存在）
    """
    if config_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.yaml")

    config_dir = os.path.dirname(config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=config_dir or None,
        prefix=".config_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp_path, config_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


_config_manager: "YAMLConfigManager | None" = None
try:
    from app.integrated_app.optimization.engine.framework_engineering import YAMLConfigManager

    _config_manager = YAMLConfigManager()
except Exception:
    _config_manager = None
