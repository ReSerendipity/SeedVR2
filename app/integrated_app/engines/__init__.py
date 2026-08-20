#!/usr/bin/env python3
"""SeedVR2 推理引擎包

提供视频/图像修复推理引擎的 Protocol 接口与具体实现。

本包包含:
- engine_interface: 三层 Protocol 抽象（RestoreEngine / BatchRestoreEngine / EngineRegistry）
  与 RestoreResult 数据结构，定义所有引擎必须遵循的统一接口契约
- seedvr2_engine: SeedVR2 模型的核心推理实现，支持视频和图像修复

引擎设计原则:
- Protocol 化接口: 所有引擎通过结构化类型满足 RestoreEngine / BatchRestoreEngine 协议，
  无需显式继承，支持 isinstance() 运行时能力检查
- 进度报告: 通过 ProgressTracker 实时追踪 VAE Encode / DiT Sampling / VAE Decode / Post-process 各阶段
- 可取消: 支持 CancellationToken 机制，在阶段切换点主动检查取消信号
- GPU 管理: 集成 BlockSwap 显存优化，支持大模型在有限显存下运行

注意: SeedVR2 模型仅支持 NVIDIA CUDA GPU 推理，不支持 CPU 推理。
"""

from .seedvr2_engine import SeedVR2Engine

__all__ = ["SeedVR2Engine"]
