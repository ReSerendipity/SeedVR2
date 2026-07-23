#!/usr/bin/env python3
"""Klar - 配置加载模块"""
import contextlib
import os
import tempfile

import yaml


def load_config(config_path=None):
    """加载配置文件（返回原始字典，向后兼容）

    内部调用 load_validated_config 进行 Pydantic 验证，
    确保配置值的类型和范围正确，过滤未知字段。
    验证失败时回退到原始 YAML 加载，避免阻塞启动。
    """
    try:
        validated = load_validated_config(config_path)
        return validated.model_dump()
    except Exception:
        # 验证失败时回退到原始加载，保证向后兼容
        if config_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(project_root, "config.yaml")

        if not os.path.exists(config_path):
            return {}

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


def load_validated_config(config_path=None):
    """加载并验证配置文件，返回 AppConfig 实例

    使用 Pydantic 模型进行验证，自动过滤未知字段。

    Args:
        config_path: 配置文件路径，默认为项目根目录的 config.yaml

    Returns:
        验证后的 AppConfig 实例
    """
    from .config_models import AppConfig

    if config_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.yaml")

    if not os.path.exists(config_path):
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(**raw)


def get_app_config(config_path=None):
    """获取验证后的 AppConfig 实例

    Args:
        config_path: 配置文件路径，默认为项目根目录的 config.yaml

    Returns:
        验证后的 AppConfig 实例
    """
    return load_validated_config(config_path)


def save_config(config, config_path=None):
    """保存配置文件（原子写入，避免半写状态）"""
    if config_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(project_root, "config.yaml")

    # 确保目标目录存在
    config_dir = os.path.dirname(config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)

    # 写入临时文件，然后原子替换
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
        # 写入失败时清理临时文件
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
