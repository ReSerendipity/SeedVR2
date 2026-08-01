#!/usr/bin/env python3
"""SeedVR2 预训练模型下载脚本。

本模块提供从 HuggingFace Hub 自动下载 SeedVR2 视频修复模型的功能，
支持 3B 和 7B 两种参数规模的模型，支持断点续传。

核心技术栈:
    - Python 3.10+
    - huggingface_hub (模型下载)
    - argparse (命令行参数解析)

命令行用法:
    python scripts/download_model.py --size 3b --save-dir pretrained_models
    python scripts/download_model.py --size 7b
"""

import argparse
import os


def download_model(model_size: str = "3b", save_dir: str = "pretrained_models") -> None:
    """从 HuggingFace Hub 下载 SeedVR2 预训练模型。

    支持下载 3B 和 7B 两种参数规模的模型，模型文件包括配置文件(.json)、
    模型权重(.safetensors/.pth/.bin)以及代码和文档文件。支持断点续传，
    不使用符号链接以兼容 Windows 平台。

    Args:
        model_size: 模型参数规模，可选值为 "3b" 或 "7b"。默认为 "3b"。
        save_dir: 模型保存的根目录路径。默认为 "pretrained_models"。

    Returns:
        None

    Raises:
        ImportError: 当 huggingface_hub 未安装时，打印提示信息后静默返回。
        ValueError: 当 model_size 不在支持的列表中时，打印错误信息后静默返回。
        Exception: 下载过程中网络或磁盘IO异常时由 snapshot_download 抛出。
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("请先安装 huggingface_hub: pip install huggingface_hub")
        return

    repo_map = {
        "3b": "ByteDance-Seed/SeedVR2-3B",
        "7b": "ByteDance-Seed/SeedVR2-7B",
    }

    if model_size not in repo_map:
        print(f"无效的模型大小: {model_size}，可选: {list(repo_map.keys())}")
        return

    repo_id = repo_map[model_size]
    local_dir = os.path.join(save_dir, f"SeedVR2-{model_size.upper()}")
    os.makedirs(local_dir, exist_ok=True)

    print(f"正在下载 {repo_id} 到 {local_dir}...")
    snapshot_download(
        cache_dir=os.path.join(local_dir, "cache"),
        local_dir=local_dir,
        repo_id=repo_id,
        local_dir_use_symlinks=False,
        resume_download=True,
        allow_patterns=["*.json", "*.safetensors", "*.pth", "*.bin", "*.py", "*.md", "*.txt"],
    )
    print(f"模型下载完成: {local_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedVR2 模型下载工具")
    parser.add_argument("--size", default="3b", choices=["3b", "7b"], help="模型大小")
    parser.add_argument("--save-dir", default="pretrained_models", help="保存目录")
    args = parser.parse_args()
    download_model(args.size, args.save_dir)
