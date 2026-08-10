"""Test data factories using factory_boy

Provides reusable test data generation for HistoryRecord, TaskRecord,
and other domain objects to reduce boilerplate in test files.
"""

from __future__ import annotations

import pytest

try:
    import factory
    FACTORY_BOY_AVAILABLE = True
except ImportError:
    FACTORY_BOY_AVAILABLE = False

from bin.integrated_app.history_db import HistoryRecord, TaskRecord

pytestmark = pytest.mark.skipif(
    not FACTORY_BOY_AVAILABLE,
    reason="factory-boy not installed (pip install factory-boy)",
)


if FACTORY_BOY_AVAILABLE:
    class HistoryRecordFactory(factory.Factory):
        """Factory for HistoryRecord test data generation."""

        class Meta:
            model = HistoryRecord

        task_type = "video"
        input_file = factory.Sequence(lambda n: f"/input/test_video_{n}.mp4")
        output_file = factory.Sequence(lambda n: f"/output/restored_{n}.mp4")
        model_size = "3b"
        status = "completed"
        parameters = "{}"
        processing_time = factory.LazyAttribute(lambda obj: 10.0 + hash(obj.input_file) % 50)

    class TaskRecordFactory(factory.Factory):
        """Factory for TaskRecord test data generation."""

        class Meta:
            model = TaskRecord

        task_id = factory.Sequence(lambda n: f"task-{n:06d}")
        record_id = 1
        status = "pending"
        progress = 0.0

    class TestHistoryRecordFactory:
        """Test the HistoryRecordFactory"""

        def test_factory_creates_valid_record(self):
            """Factory should create a valid HistoryRecord"""
            record = HistoryRecordFactory()
            assert record.task_type == "video"
            assert record.input_file.startswith("/input/")
            assert record.status == "completed"

        def test_factory_sequence_increment(self):
            """Factory sequence should increment"""
            r1 = HistoryRecordFactory()
            r2 = HistoryRecordFactory()
            assert r1.input_file != r2.input_file

        def test_factory_override(self):
            """Factory should allow field override"""
            record = HistoryRecordFactory(task_type="image", status="failed")
            assert record.task_type == "image"
            assert record.status == "failed"

        def test_factory_batch(self):
            """Factory should support batch creation"""
            records = HistoryRecordFactory.create_batch(5)
            assert len(records) == 5
            assert len({r.input_file for r in records}) == 5

        def test_factory_custom_model_size(self):
            """Factory should support custom model size"""
            record = HistoryRecordFactory(model_size="7b")
            assert record.model_size == "7b"

    class TestTaskRecordFactory:
        """Test the TaskRecordFactory"""

        def test_factory_creates_valid_task(self):
            """Factory should create a valid TaskRecord"""
            task = TaskRecordFactory()
            assert task.task_id.startswith("task-")
            assert task.status == "pending"
            assert task.progress == 0.0

        def test_factory_override_status(self):
            """Factory should allow status override"""
            task = TaskRecordFactory(status="completed", progress=100.0)
            assert task.status == "completed"
            assert task.progress == 100.0

        def test_factory_batch_unique_ids(self):
            """Factory batch should produce unique task_ids"""
            tasks = TaskRecordFactory.create_batch(10)
            ids = {t.task_id for t in tasks}
            assert len(ids) == 10
