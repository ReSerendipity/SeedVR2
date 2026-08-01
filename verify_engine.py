"""SeedVR2 引擎最小自检脚本（非破坏性）。

用途：在不加载真实模型权重、不分配 GPU 显存的前提下，快速验证引擎运行前提是否就绪。
覆盖三项核心检查：
    1. 配置加载与 Pydantic 校验（只读 config.yaml）
    2. NVIDIA CUDA GPU 后端检测（仅查询，不分配显存）
    3. 引擎模块导入与实例化（延迟加载策略下不加载大模型权重）

任一核心检查失败即以非零退出码结束，供 run_verify.bat 判定成败。
本脚本绝不调用 load_model()，也不触发任何真实推理或显存分配。
"""

import os
import sys
import traceback

# 将项目根目录插入 sys.path 首位，保证 `from bin.integrated_app.xxx import` 绝对导入可用
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"[INFO] {msg}")


def check_config() -> bool:
    """检查 1：只读加载并校验 config.yaml。"""
    try:
        from bin.integrated_app.config import get_app_config, load_config

        config = load_config()
        app_config = get_app_config()
        default_size = app_config.model.default_size
        _ok(f"config loaded and validated (default model size: {default_size})")
        return bool(config is not None)
    except Exception as e:
        _fail(f"config load/validate failed: {e}")
        traceback.print_exc()
        return False


def check_gpu_backend() -> bool:
    """检查 2：CUDA 后端检测（仅查询，不分配显存）。

    未检测到 NVIDIA GPU 时以警告形式报告降级模式，但不视为脚本失败——
    脚本本身运行成功，能明确告知调用者 GPU 是否可用即达成自检目的。
    """
    try:
        from bin.integrated_app.gpu_backend import gpu_manager

        if gpu_manager.is_gpu_available:
            info = gpu_manager.get_gpu_info()
            _ok(f"CUDA GPU available: {gpu_manager.device_name} " f"({info.total_vram_mb} MB total VRAM)")
        else:
            _info("no NVIDIA GPU detected -> degraded mode " "(SeedVR2 inference requires NVIDIA CUDA GPU)")
        return True
    except Exception as e:
        _fail(f"GPU backend detection raised an unexpected error: {e}")
        traceback.print_exc()
        return False


def check_engine() -> bool:
    """检查 3：引擎模块导入与实例化（不加载大模型权重）。"""
    try:
        from bin.integrated_app.config import load_config
        from bin.integrated_app.engines.seedvr2_engine import SeedVR2Engine

        engine = SeedVR2Engine(load_config())
        if engine.is_loaded():
            _fail("engine reports loaded=True right after construction (unexpected)")
            return False
        _ok("engine module imported and instantiated (no model weights loaded)")
        return True
    except Exception as e:
        _fail(f"engine import/instantiation failed: {e}")
        traceback.print_exc()
        return False


def main() -> int:
    print("=== SeedVR2 engine self-check (non-destructive) ===")
    checks = [
        ("config", check_config),
        ("gpu-backend", check_gpu_backend),
        ("engine", check_engine),
    ]
    results = []
    for name, fn in checks:
        results.append((name, fn()))

    print("=== summary ===")
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAIL'}")

    if failed:
        print(f"[RESULT] FAILED checks: {', '.join(failed)}")
        return 1
    print("[RESULT] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
