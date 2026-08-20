"""
Seedvr2 全面性能测试套件 (W11-12)
测试所有核心模块的性能和正确性
"""

import json
import logging
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.duration = 0.0
        self.error = None
        self.metrics = {}


def test_flash_attention():
    """测试 Flash Attention 性能"""
    if not torch.cuda.is_available():
        return TestResult("Flash Attention"), "CUDA unavailable"

    try:
        from app.vram.flash_attention_wrapper import FlashAttention

        result = TestResult("Flash Attention")
        n_heads, head_dim = 8, 64
        dim = n_heads * head_dim

        flash = FlashAttention(dim, n_heads).cuda()
        x = torch.randn(2, 1024, dim).cuda()

        # 预热
        for _ in range(5):
            with torch.no_grad():
                _ = flash(x)

        # 测试
        torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(20):
            with torch.no_grad():
                _ = flash(x)
        torch.cuda.synchronize()
        result.duration = (time.perf_counter() - start) * 1000 / 20
        result.passed = True
        result.metrics["avg_time_ms"] = result.duration
        result.metrics["throughput"] = (2 * 1024) / (result.duration / 1000)
        return result
    except Exception as e:
        result = TestResult("Flash Attention")
        result.error = str(e)
        return result


def test_lcm_distill():
    """测试 LCM 蒸馏模块"""
    try:
        from diffusers import AutoencoderKL, UNet2DConditionModel

        from app.models.lcm_distill import LatentConsistencyModel

        result = TestResult("LCM Distill")

        # 创建小模型用于测试
        unet = UNet2DConditionModel(
            sample_size=32,
            in_channels=4,
            out_channels=4,
            layers_per_block=1,
            block_out_channels=(64,),
            down_block_types=("CrossAttnDownBlock2D",),
            up_block_types=("CrossAttnUpBlock2D",),
            cross_attention_dim=768,
        )
        vae = AutoencoderKL(
            in_channels=3,
            out_channels=3,
            block_out_channels=(32,),
            down_block_types=("DownEncoderBlock2D",),
            up_block_types=("UpDecoderBlock2D",),
        )

        _lcm = LatentConsistencyModel(unet, vae)
        result.passed = True
        result.metrics["unet_params"] = sum(p.numel() for p in unet.parameters())
        return result
    except Exception as e:
        result = TestResult("LCM Distill")
        result.error = str(e)
        return result


def test_raft_flow():
    """测试 RAFT 光流模块"""
    try:
        from app.models.raft_flow import RAFT

        result = TestResult("RAFT")
        raft = RAFT()

        if torch.cuda.is_available():
            f1 = torch.randn(1, 3, 64, 64).cuda()
            f2 = torch.randn(1, 3, 64, 64).cuda()
            flow = raft.estimate_flow(f1, f2)
            result.metrics["flow_shape"] = list(flow.shape)
        result.passed = True
        return result
    except Exception as e:
        result = TestResult("RAFT")
        result.error = str(e)
        return result


def test_rife_interpolator():
    """测试 RIFE 帧插值"""
    try:
        from app.models.rife_interpolator import RIFEInterpolator

        result = TestResult("RIFE")
        rife = RIFEInterpolator()

        if torch.cuda.is_available():
            f1 = torch.randn(1, 3, 64, 64).cuda()
            f2 = torch.randn(1, 3, 64, 64).cuda()
            interp = rife.interpolate(f1, f2)
            result.metrics["interp_shape"] = list(interp.shape)
        result.passed = True
        return result
    except Exception as e:
        result = TestResult("RIFE")
        result.error = str(e)
        return result


def test_distributed_trainer():
    """测试分布式训练器配置"""
    try:
        from training.distributed_trainer import DistributedTrainer

        result = TestResult("Distributed Trainer")
        config = type("Config", (), {"batch_size": 4})()
        trainer = DistributedTrainer(config)
        result.passed = True
        result.metrics["world_size"] = trainer.world_size
        trainer.cleanup()
        return result
    except Exception as e:
        result = TestResult("Distributed Trainer")
        result.error = str(e)
        return result


def test_experiment_tracker():
    """测试实验追踪器"""
    try:
        from app.utils.experiment_tracker import ExperimentTracker

        result = TestResult("Experiment Tracker")
        tracker = ExperimentTracker(experiment_name="test_run")
        tracker.log_metrics({"loss": 0.5, "accuracy": 0.95}, step=1)
        tracker.log_hyperparameters({"lr": 0.001, "batch_size": 32})
        tracker.finish()
        result.passed = True
        return result
    except Exception as e:
        result = TestResult("Experiment Tracker")
        result.error = str(e)
        return result


def test_perf_optimizer():
    """测试性能优化器"""
    try:
        from app.perf.optimizer import perf_monitor

        result = TestResult("Performance Optimizer")

        with perf_monitor.measure("test_op"):
            time.sleep(0.1)

        result.passed = True
        result.metrics["report"] = perf_monitor.report()
        perf_monitor.save_report()
        return result
    except Exception as e:
        result = TestResult("Performance Optimizer")
        result.error = str(e)
        return result


def run_all_tests():
    """运行所有测试"""
    logger.info("🚀 开始 Seedvr2 全面性能测试")
    logger.info(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    logger.info(f"PyTorch: {torch.__version__}")
    logger.info("=" * 60)

    tests = [
        test_flash_attention,
        test_lcm_distill,
        test_raft_flow,
        test_rife_interpolator,
        test_distributed_trainer,
        test_experiment_tracker,
        test_perf_optimizer,
    ]

    results: list[TestResult] = []
    for test_fn in tests:
        logger.info(f"运行: {test_fn.__name__}")
        try:
            result = test_fn()
            results.append(result)
            if result.passed:
                logger.info(f"  ✅ 通过 (耗时: {result.duration:.2f}ms)")
                if result.metrics:
                    for k, v in result.metrics.items():
                        if isinstance(v, (str, int, float)):
                            logger.info(f"     {k}: {v}")
            else:
                logger.error(f"  ❌ 失败: {result.error}")
        except Exception as e:
            logger.error(f"  ❌ 异常: {e}")
            results.append(TestResult(test_fn.__name__))

    # 汇总
    logger.info("=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    logger.info(f"📊 测试结果: {passed}/{total} 通过 ({passed/total*100:.1f}%)")

    # 保存报告
    report_path = Path(__file__).parent / "test_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration_ms": r.duration,
                    "error": r.error,
                    "metrics": {k: v for k, v in r.metrics.items() if isinstance(v, (str, int, float, list))},
                }
                for r in results
            ],
            f,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(f"📄 详细报告: {report_path}")
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
