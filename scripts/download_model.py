#!/usr/bin/env python3
"""SeedVR2 预训练模型下载脚本。

从 HuggingFace 下载与 config.yaml 引用的文件名完全一致的权重文件，
并直接保存到 pretrained_models/ 根目录（与 model_manager / engine 的
查找逻辑对齐，见 bin/integrated_app/model_manager.py check_model_exists）。

命令行用法:
    # 下载 3B + VAE + 文本嵌入（默认行为，完整可运行最小集合）
    python scripts/download_model.py --size 3b

    # 下载 7B 或 7B-Sharp
    python scripts/download_model.py --size 7b
    python scripts/download_model.py --size 7b_sharp

    # 指定自定义保存目录
    python scripts/download_model.py --size 3b --save-dir D:/shared_models

    # 只下主权重，不下共享的 VAE / 嵌入
    python scripts/download_model.py --size 3b --no-vae

特性:
    - 幂等：已存在的文件自动跳过，不会重复下载
    - 断点续传：由 huggingface_hub 内部机制保证
    - 文件名与 config.yaml 中 model.models.<size> 的引用完全一致，
      下载完成后无需任何改名/移动即可被应用识别
"""

import argparse
import importlib.util
from pathlib import Path

# 各模型尺寸对应的权重文件名（与 config.yaml model.models.<size> 保持一致）
_MODEL_FILES: dict[str, list[str]] = {
    "3b": [
        "seedvr2_ema_3b_fp16.safetensors",
        "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    ],
    "7b": [
        "seedvr2_ema_7b_fp16.safetensors",
        "seedvr2_ema_7b_fp8_e4m3fn.safetensors",
    ],
    "7b_sharp": [
        "seedvr2_ema_7b_sharp_fp16.safetensors",
        "seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors",
    ],
}

# 所有尺寸共用的 VAE 与文本嵌入文件（config.yaml 每个尺寸都会引用）
_SHARED_FILES: list[str] = [
    "ema_vae_fp16.safetensors",
    "pos_emb.pt",
    "neg_emb.pt",
]

# 默认下载来源仓库（社区整理的 ComfyUI 版，文件名与上述清单完全一致）
# 可通过 --repo 覆盖为其他镜像仓库
_DEFAULT_REPO = "numz/SeedVR2_comfyUI"


def _download_file(
    repo_id: str, filename: str, save_dir: Path, allow_missing: bool = False
) -> bool:
    """下载单个文件到 save_dir，已存在则跳过。

    Args:
        repo_id: HuggingFace 仓库 ID。
        filename: 仓库内的文件名。
        save_dir: 保存目录（文件直接写入该目录根下）。
        allow_missing: 仓库中缺失该文件时是否允许静默跳过（用于 VAE/嵌入等
                      可能位于其他仓库的文件）。

    Returns:
        bool: 下载或已存在返回 True；仓库缺失且 allow_missing 时返回 False。
    """
    from huggingface_hub import hf_hub_download

    target = save_dir / filename
    if target.exists() and target.stat().st_size > 0:
        print(f"  [跳过] 已存在: {target.name} ({target.stat().st_size / 1024**3:.2f} GB)")
        return True

    try:
        print(f"  [下载] {filename} ...")
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(save_dir),
            local_dir_use_symlinks=False,
        )
        print(f"  [完成] {filename}")
        return True
    except Exception as e:
        if allow_missing:
            print(f"  [跳过] 仓库中未找到 {filename}（不影响其他文件）: {e}")
            return False
        raise


def download_model(model_size: str = "3b", save_dir: str = "pretrained_models", repo_id: str = _DEFAULT_REPO, with_vae: bool = True) -> None:
    """从 HuggingFace 下载指定尺寸的 SeedVR2 模型权重到根目录。

    Args:
        model_size: 模型参数规模，可选 "3b" / "7b" / "7b_sharp"。默认为 "3b"。
        save_dir: 模型保存的根目录路径（权重文件直接写入该目录根下）。默认为 "pretrained_models"。
        repo_id: HuggingFace 仓库 ID，默认为社区整理仓库 numz/SeedVR2_comfyUI。
        with_vae: 是否同时下载共享的 VAE 与文本嵌入文件。默认为 True。

    Returns:
        None

    Raises:
        ValueError: model_size 不在支持列表时抛出。
    """
    if importlib.util.find_spec("huggingface_hub") is None:
        print("请先安装 huggingface_hub: pip install huggingface_hub")
        return

    if model_size not in _MODEL_FILES:
        print(f"无效的模型大小: {model_size}，可选: {list(_MODEL_FILES.keys())}")
        return

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    files = list(_MODEL_FILES[model_size])
    if with_vae:
        files += _SHARED_FILES

    print(f"来源仓库: {repo_id}")
    print(f"保存目录: {save_path.resolve()}")
    print(f"共 {len(files)} 个文件（已存在会自动跳过）:")
    print()

    for filename in files:
        # VAE / 嵌入文件在主仓库缺失时允许跳过（它们也可能位于官方仓库）
        _download_file(repo_id, filename, save_path, allow_missing=filename in _SHARED_FILES)

    print()
    print("=" * 60)
    print("下载结束。请确认以下文件都已存在于保存目录根下：")
    for f in files:
        mark = "✓" if (save_path / f).exists() else "✗"
        print(f"  {mark} {f}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedVR2 模型下载工具")
    parser.add_argument(
        "--size",
        default="3b",
        choices=["3b", "7b", "7b_sharp"],
        help="模型大小 (默认 3b)",
    )
    parser.add_argument("--save-dir", default="pretrained_models", help="保存目录 (默认 pretrained_models)")
    parser.add_argument("--repo", default=_DEFAULT_REPO, help="HuggingFace 仓库 ID (默认 numz/SeedVR2_comfyUI)")
    parser.add_argument(
        "--no-vae",
        action="store_true",
        help="不下载共享的 VAE / 文本嵌入文件",
    )
    args = parser.parse_args()
    download_model(args.size, args.save_dir, args.repo, with_vae=not args.no_vae)
