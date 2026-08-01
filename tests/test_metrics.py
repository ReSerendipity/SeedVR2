"""性能指标收集器单元测试

覆盖 MetricsCollector 的推理记录、快照生成和重置功能。
"""

import pytest

from bin.integrated_app.metrics import MetricsCollector, MetricsSnapshot


class TestMetricsCollector:
    """MetricsCollector 性能指标收集器测试"""

    def test_record_inference_success(self):
        collector = MetricsCollector()
        collector.record_inference(success=True, duration=10.5, model_size="3b")
        snap = collector.snapshot()
        assert snap.total_inferences == 1
        assert snap.successful_inferences == 1
        assert snap.failed_inferences == 0
        assert snap.avg_inference_duration == 10.5
        assert snap.last_inference_duration == 10.5

    def test_record_inference_failure(self):
        collector = MetricsCollector()
        collector.record_inference(success=False, duration=5.0, model_size="7b")
        snap = collector.snapshot()
        assert snap.total_inferences == 1
        assert snap.successful_inferences == 0
        assert snap.failed_inferences == 1

    def test_multiple_inferences(self):
        collector = MetricsCollector()
        collector.record_inference(success=True, duration=10.0)
        collector.record_inference(success=True, duration=20.0)
        collector.record_inference(success=False, duration=5.0)
        snap = collector.snapshot()
        assert snap.total_inferences == 3
        assert snap.successful_inferences == 2
        assert snap.failed_inferences == 1
        assert snap.avg_inference_duration == pytest.approx(35.0 / 3, rel=0.01)
        assert snap.last_inference_duration == 5.0

    def test_reset(self):
        collector = MetricsCollector()
        collector.record_inference(success=True, duration=10.0)
        collector.reset()
        snap = collector.snapshot()
        assert snap.total_inferences == 0
        assert snap.successful_inferences == 0
        assert snap.avg_inference_duration == 0.0

    def test_snapshot_to_dict(self):
        collector = MetricsCollector()
        collector.record_inference(success=True, duration=10.0)
        snap = collector.snapshot()
        d = snap.to_dict()
        assert "system" in d
        assert "gpu" in d
        assert "inference" in d
        assert "cache" in d
        assert d["inference"]["total"] == 1
        assert d["inference"]["successful"] == 1
        assert d["inference"]["success_rate"] == 100.0

    def test_snapshot_uptime_positive(self):
        collector = MetricsCollector()
        snap = collector.snapshot()
        assert snap.uptime_seconds > 0

    def test_history_limit(self):
        """历史记录不超过 100 条"""
        collector = MetricsCollector()
        for _ in range(150):
            collector.record_inference(success=True, duration=1.0)
        # internal deque should be capped at 100
        assert len(collector._inference_records) == 100
        # but total counter should be 150
        snap = collector.snapshot()
        assert snap.total_inferences == 150

    def test_thread_safety(self):
        """多线程并发记录不丢失数据"""
        import threading

        collector = MetricsCollector()
        threads = []

        def record_n(n):
            for _ in range(n):
                collector.record_inference(success=True, duration=1.0)

        for _ in range(10):
            t = threading.Thread(target=record_n, args=(10,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        snap = collector.snapshot()
        assert snap.total_inferences == 100


class TestMetricsSnapshot:
    """MetricsSnapshot 数据类测试"""

    def test_defaults(self):
        snap = MetricsSnapshot()
        assert snap.uptime_seconds == 0.0
        assert snap.gpu_available is False
        assert snap.total_inferences == 0

    def test_to_dict_structure(self):
        snap = MetricsSnapshot(
            uptime_seconds=100.0,
            ram_usage_pct=50.0,
            gpu_available=True,
            gpu_name="RTX 4090",
            total_inferences=10,
            successful_inferences=8,
        )
        d = snap.to_dict()
        assert d["system"]["uptime_seconds"] == 100.0
        assert d["gpu"]["available"] is True
        assert d["gpu"]["name"] == "RTX 4090"
        assert d["inference"]["total"] == 10
        assert d["inference"]["successful"] == 8
        assert d["inference"]["success_rate"] == 80.0
