#!/usr/bin/env python3
"""SeedVR2 模型下载脚本"""
import os
import argparse

def download_model(model_size="3b", save_dir="pretrained_models"):
    """从 HuggingFace 下载 SeedVR2 模型"""
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
