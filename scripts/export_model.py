#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""TorchScript / ONNX 导出脚本 (P3 长期方案)

将 SeedVR2 的 DiT / VAE 模型导出为 TorchScript (.pt) 或 ONNX (.onnx) 格式，
使推理时不需要暴露 model_lib/ 源代码，抬高逆向门槛。

导出后的模型仍然可以被 Netron 可视化，但不再暴露 Python 源码实现。

用法:
    # 导出 TorchScript
    python scripts/export_model.py --format torchscript --model 3b --output exported/

    # 导出 ONNX
    python scripts/export_model.py --format onnx --model 3b --output exported/

注意:
    - 导出需要先加载模型权重 (需要 GPU)
    - ONNX 导出对动态 shape 的支持有限，需固定输入尺寸
    - TorchScript 导出需要 trace 或 script，注意动态控制流
"""

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def export_torchscript(model_size: str, output_dir: str, precision: str = "fp16") -> None:
    """导出模型为 TorchScript 格式。

    Args:
        model_size: 模型大小标识 ("3b", "7b", "7b_sharp")。
        output_dir: 输出目录。
        precision: 精度 ("fp16" 或 "fp8")。
    """
    import torch

    from app.integrated_app.config import load_config
    from app.integrated_app.engines.seedvr2_engine import SeedVR2Engine

    config = load_config()
    engine = SeedVR2Engine(config)

    import asyncio

    asyncio.run(engine.load_model(model_size=model_size, precision=precision))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 导出 DiT
    if engine.dit is not None:
        dit_scripted = torch.jit.script(engine.dit)
        dit_path = output_path / f"seedvr2_{model_size}_dit_{precision}.pt"
        torch.jit.save(dit_scripted, str(dit_path))
        logger.info(f"DiT 已导出 (TorchScript): {dit_path}")
    else:
        logger.warning("DiT 模型未加载，跳过导出")

    # 导出 VAE
    if engine.vae is not None:
        vae_scripted = torch.jit.script(engine.vae)
        vae_path = output_path / f"seedvr2_{model_size}_vae_{precision}.pt"
        torch.jit.save(vae_scripted, str(vae_path))
        logger.info(f"VAE 已导出 (TorchScript): {vae_path}")
    else:
        logger.warning("VAE 模型未加载，跳过导出")

    asyncio.run(engine.unload_model())


def export_onnx(
    model_size: str,
    output_dir: str,
    precision: str = "fp16",
    sample_height: int = 1080,
    sample_width: int = 1920,
) -> None:
    """导出模型为 ONNX 格式。

    Args:
        model_size: 模型大小标识。
        output_dir: 输出目录。
        precision: 精度。
        sample_height: 采样高度 (用于固定输入 shape)。
        sample_width: 采样宽度。
    """
    import torch

    from app.integrated_app.config import load_config
    from app.integrated_app.engines.seedvr2_engine import SeedVR2Engine

    config = load_config()
    engine = SeedVR2Engine(config)

    import asyncio

    asyncio.run(engine.load_model(model_size=model_size, precision=precision))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # ONNX 导出需要固定输入 shape
    # VAE 导出 (编码器)
    if engine.vae is not None:
        vae_path = output_path / f"seedvr2_{model_size}_vae_{precision}.onnx"
        dummy_input = torch.randn(1, 3, sample_height, sample_width, device=engine.device)

        torch.onnx.export(
            engine.vae,
            dummy_input,
            str(vae_path),
            export_params=True,
            opset_version=17,
            do_constant_folding=True,
            input_names=["input"],
            output_names=["output"],
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        )
        logger.info(f"VAE 已导出 (ONNX): {vae_path}")

    asyncio.run(engine.unload_model())


def main():
    parser = argparse.ArgumentParser(description="SeedVR2 模型导出工具")
    parser.add_argument("--format", choices=["torchscript", "onnx"], required=True, help="导出格式")
    parser.add_argument("--model", default="3b", help="模型大小 (3b/7b/7b_sharp)")
    parser.add_argument("--precision", default="fp16", help="精度 (fp16/fp8)")
    parser.add_argument("--output", default="exported_models", help="输出目录")
    parser.add_argument("--height", type=int, default=1080, help="ONNX 采样高度")
    parser.add_argument("--width", type=int, default=1920, help="ONNX 采样宽度")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.format == "torchscript":
        export_torchscript(args.model, args.output, args.precision)
    else:
        export_onnx(args.model, args.output, args.precision, args.height, args.width)

    logger.info("导出完成")


if __name__ == "__main__":
    main()
