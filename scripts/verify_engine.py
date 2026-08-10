#!/usr/bin/env python3
"""SeedVR2 引擎自检脚本。

快速验证部署环境是否可以正常运行推理：
1. 检查 Python 版本和关键依赖
2. 检查 NVIDIA GPU 和 CUDA 可用性
3. 检查模型文件完整性（SHA256 校验）
4. 检查模型是否能成功加载
5. 执行一次小分辨率推理测试（可选）

Usage:
    python scripts/verify_engine.py [--model 3b] [--precision fp16] [--skip-infer]

退出码：
    0 — 全部检查通过
    1 — 检查失败（详见输出）
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(title: str):
    """打印分区标题。"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_ok(msg: str):
    """打印成功信息。"""
    print(f"  [OK] {msg}")


def print_fail(msg: str):
    """打印失败信息。"""
    print(f"  [FAIL] {msg}")


def print_warn(msg: str):
    """打印警告信息。"""
    print(f"  [WARN] {msg}")


def print_info(msg: str):
    """打印信息。"""
    print(f"  [INFO] {msg}")


def check_python_version() -> bool:
    """检查 Python 版本。"""
    print_header("1. Python 版本检查")
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    print_info(f"Python {version_str} ({sys.executable})")

    if version.major == 3 and version.minor >= 12:
        print_ok(f"Python {version_str} >= 3.12 ✓")
        return True
    else:
        print_fail(f"Python {version_str} < 3.12，需要 Python 3.12+")
        return False


def check_dependencies() -> bool:
    """检查关键依赖包是否安装。"""
    print_header("2. 依赖检查")
    required = {
        "fastapi": "FastAPI Web 框架",
        "uvicorn": "ASGI 服务器",
        "torch": "PyTorch 深度学习框架",
        "torchvision": "PyTorch 视觉工具",
        "jinja2": "Jinja2 模板引擎",
        "aiosqlite": "异步 SQLite 驱动",
        "pydantic": "数据验证",
        "PIL": "Pillow 图像处理",
        "cv2": "OpenCV 视频处理",
        "safetensors": "安全权重加载",
        "einops": "张量操作",
        "omegaconf": "配置管理",
        "psutil": "系统信息",
        "yaml": "YAML 配置",
    }

    all_ok = True
    for module, desc in required.items():
        try:
            __import__(module)
            print_ok(f"{module} — {desc}")
        except ImportError:
            print_fail(f"{module} — {desc} (未安装)")
            all_ok = False

    return all_ok


def check_gpu() -> bool:
    """检查 NVIDIA GPU 和 CUDA 可用性。"""
    print_header("3. GPU 检查")

    try:
        import torch

        if not torch.cuda.is_available():
            print_fail("CUDA 不可用！SeedVR2 需要 NVIDIA GPU。")
            print_info("请检查：1) NVIDIA 驱动已安装  2) CUDA Toolkit 已安装  3) PyTorch 已编译 CUDA 支持")
            return False

        gpu_count = torch.cuda.device_count()
        print_ok(f"CUDA 可用，检测到 {gpu_count} 个 GPU")
        print_info(f"CUDA 版本: {torch.version.cuda}")

        for i in range(gpu_count):
            props = torch.cuda.get_device_properties(i)
            total_gb = props.total_memory / (1024**3)
            print_ok(f"GPU {i}: {props.name} ({total_gb:.1f} GB)")

        return True

    except Exception as e:
        print_fail(f"GPU 检查异常: {e}")
        return False


def check_model_files(model_size: str, precision: str) -> bool:
    """检查模型文件是否存在。"""
    print_header(f"4. 模型文件检查 ({model_size}/{precision})")

    try:
        import yaml
    except ImportError:
        print_fail("PyYAML 未安装，无法读取配置")
        return False

    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        print_fail(f"配置文件不存在: {config_path}")
        return False

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    models_cfg = config.get("model", {}).get("models", {})
    model_cfg = models_cfg.get(model_size, {})

    if not model_cfg:
        print_fail(f"配置中未找到模型: {model_size}")
        return False

    print_info(f"模型名称: {model_cfg.get('name', 'N/A')}")
    print_info(f"配置目录: {model_cfg.get('config_dir', 'N/A')}")
    print_info(f"Block 数量: {model_cfg.get('num_blocks', 'N/A')}")

    pretrained_dir = PROJECT_ROOT / config.get("model", {}).get("pretrained_dir", "pretrained_models")

    # 检查主要权重文件
    checkpoint_key = f"checkpoint_{precision}"
    checkpoint_name = model_cfg.get(checkpoint_key, "")
    if not checkpoint_name:
        print_fail(f"配置中未找到 {checkpoint_key}")
        return False

    checkpoint_path = pretrained_dir / checkpoint_name
    if not checkpoint_path.exists():
        print_fail(f"权重文件不存在: {checkpoint_path}")
        print_info("请从 ByteDance-Seed HuggingFace 下载模型权重")
        return False

    file_size_mb = checkpoint_path.stat().st_size / (1024 * 1024)
    print_ok(f"权重文件: {checkpoint_name} ({file_size_mb:.1f} MB)")

    # SHA256 校验（如果配置了）
    sha_key = f"sha256_{precision}"
    expected_sha = model_cfg.get(sha_key, "")
    if expected_sha:
        print_info("正在计算 SHA256...")
        sha256 = hashlib.sha256()
        with open(checkpoint_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        actual_sha = sha256.hexdigest()
        if actual_sha == expected_sha:
            print_ok("SHA256 校验通过 ✓")
        else:
            print_fail("SHA256 校验失败！")
            print_info(f"  期望: {expected_sha}")
            print_info(f"  实际: {actual_sha}")
            return False
    else:
        print_warn(f"未配置 {sha_key}，跳过 SHA256 校验")

    # 检查 VAE 权重
    vae_name = model_cfg.get("vae_checkpoint", "")
    if vae_name:
        vae_path = pretrained_dir / vae_name
        if vae_path.exists():
            vae_size_mb = vae_path.stat().st_size / (1024 * 1024)
            print_ok(f"VAE 权重: {vae_name} ({vae_size_mb:.1f} MB)")
        else:
            print_fail(f"VAE 权重不存在: {vae_path}")
            return False

    # 检查 embedding 文件
    for emb_key in ("pos_emb", "neg_emb"):
        emb_name = model_cfg.get(emb_key, "")
        if emb_name:
            emb_path = pretrained_dir / emb_name
            if emb_path.exists():
                print_ok(f"Embedding: {emb_name}")
            else:
                print_warn(f"Embedding 文件不存在: {emb_path}")
                print_info("  （某些模型可能不需要 embedding 文件，可忽略此警告）")

    return True


def check_model_load(model_size: str, precision: str) -> bool:
    """检查模型是否能成功加载。"""
    print_header(f"5. 模型加载测试 ({model_size}/{precision})")

    try:
        from bin.integrated_app.gpu_backend import gpu_manager
        from bin.integrated_app.model_manager import ModelManager

        if not gpu_manager.is_gpu_available:
            print_fail("GPU 不可用，无法加载模型")
            return False

        manager = ModelManager()
        print_info(f"正在加载模型 {model_size}/{precision}...")
        print_info("（这可能需要几分钟时间，请耐心等待）")

        start_time = time.time()
        import asyncio

        result = asyncio.run(manager.load_model(model_size=model_size, precision=precision))
        elapsed = time.time() - start_time

        if result.get("loaded") or result.get("status") == "ok":
            print_ok(f"模型加载成功！耗时 {elapsed:.1f}s")
            return True
        else:
            print_fail(f"模型加载失败: {result}")
            return False

    except Exception as e:
        print_fail(f"模型加载异常: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_inference_test(model_size: str, precision: str) -> bool:
    """执行一次小分辨率推理测试。"""
    print_header(f"6. 推理测试 ({model_size}/{precision})")

    try:
        import numpy as np
        from PIL import Image

        from bin.integrated_app.model_registry import model_registry

        if not model_registry.model_loaded:
            print_fail("模型未加载，无法执行推理测试")
            return False

        # 创建一张小测试图片（128x128 随机噪声）
        test_dir = PROJECT_ROOT / "data" / "uploads" / "image"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_image_path = test_dir / "verify_engine_test.png"

        random_array = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
        Image.fromarray(random_array).save(test_image_path)
        print_info(f"测试图片已创建: {test_image_path}")

        output_dir = PROJECT_ROOT / "outputs" / "image"
        output_dir.mkdir(parents=True, exist_ok=True)

        engine = model_registry.get_engine()
        if engine is None:
            print_fail("引擎实例不可用")
            return False

        from bin.integrated_app.engines.seedvr2_engine import ImageInferenceConfig

        config = ImageInferenceConfig()
        print_info("开始推理...")
        start_time = time.time()
        result = asyncio.run(
            engine.infer_image(
                image_path=str(test_image_path),
                output_dir=str(output_dir),
                config=config,
            )
        )
        elapsed = time.time() - start_time

        if result.success:
            print_ok(f"推理成功！耗时 {elapsed:.1f}s")
            print_info(f"输出文件: {result.output_path}")
            # 清理测试文件
            test_image_path.unlink(missing_ok=True)
            return True
        else:
            print_fail(f"推理失败: {result.error}")
            return False

    except Exception as e:
        print_fail(f"推理测试异常: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="SeedVR2 引擎自检脚本")
    parser.add_argument("--model", default="3b", choices=["3b", "7b", "7b_sharp"], help="模型尺寸")
    parser.add_argument("--precision", default="fp16", choices=["fp16", "fp8"], help="精度")
    parser.add_argument("--skip-infer", action="store_true", help="跳过推理测试")
    args = parser.parse_args()

    print_header("SeedVR2 引擎自检")
    print_info(f"项目路径: {PROJECT_ROOT}")
    print_info(f"模型: {args.model} / 精度: {args.precision}")

    results = []

    # 1. Python 版本
    results.append(("Python 版本", check_python_version()))

    # 2. 依赖检查
    results.append(("依赖包", check_dependencies()))

    # 3. GPU 检查
    results.append(("GPU", check_gpu()))

    # 4. 模型文件检查
    results.append(("模型文件", check_model_files(args.model, args.precision)))

    # 5. 模型加载测试
    if all(r[1] for r in results):
        results.append(("模型加载", check_model_load(args.model, args.precision)))
    else:
        print_warn("前置检查未通过，跳过模型加载测试")
        results.append(("模型加载", False))

    # 6. 推理测试
    if all(r[1] for r in results) and not args.skip_infer:
        results.append(("推理测试", run_inference_test(args.model, args.precision)))
    elif not args.skip_infer:
        print_warn("前置检查未通过，跳过推理测试")
        results.append(("推理测试", False))
    else:
        print_info("已跳过推理测试 (--skip-infer)")

    # 总结
    print_header("自检结果总结")
    all_pass = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print_ok("全部检查通过！SeedVR2 已准备好运行。")
        sys.exit(0)
    else:
        print_fail("部分检查未通过，请根据上述信息排查问题。")
        sys.exit(1)


if __name__ == "__main__":
    main()
