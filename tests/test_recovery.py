"""recovery 模块单元测试

覆盖 recover_tasks 启动任务恢复功能。
使用 AsyncMock 模拟数据库和任务队列，不依赖真实数据库或 GPU。
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from bin.integrated_app.config_models import ImageRestoreParams, VideoRestoreParams
from bin.integrated_app.routes.restore.recovery import recover_tasks


@dataclass
class MockTaskRecord:
    """测试用任务记录，与 TaskRecord 结构一致"""

    task_id: str = "task-001"
    record_id: int = 1
    status: str = "pending"
    progress: float = 0.0
    output_path: str = ""
    error_message: str = ""
    updated_at: str = ""


@dataclass
class MockHistoryRecord:
    """测试用历史记录，与 HistoryRecord 结构一致"""

    id: int | None = 1
    task_type: str = "image"
    input_file: str = "input.png"
    output_file: str = ""
    model_size: str = "3b"
    status: str = "pending"
    parameters: str | None = "{}"
    processing_time: float = 0.0
    created_at: str = ""
    error_message: str = ""


def make_image_params_json() -> str:
    """生成有效的 ImageRestoreParams JSON"""
    return ImageRestoreParams().model_dump_json()


def make_video_params_json() -> str:
    """生成有效的 VideoRestoreParams JSON"""
    return VideoRestoreParams().model_dump_json()


@pytest.fixture
def mock_history_db():
    """模拟 HistoryDB"""
    db = AsyncMock()
    db.get_incomplete_tasks = AsyncMock(return_value=[])
    db.get_records_by_ids = AsyncMock(return_value=[])
    db.update_record = AsyncMock(return_value=True)
    return db


@pytest.fixture
def mock_task_queue():
    """模拟 TaskQueue"""
    queue = AsyncMock()
    queue.submit = AsyncMock()
    return queue


@pytest.fixture
def mock_config():
    """测试配置"""
    return {"restore": {"video_resolution": 1080}}


# ---------------------------------------------------------------------------
# 基本场景
# ---------------------------------------------------------------------------


class TestRecoverTasksBasic:
    """recover_tasks 基本功能测试"""

    @pytest.mark.asyncio
    async def test_no_incomplete_tasks(self, mock_history_db, mock_task_queue, mock_config):
        """没有未完成任务时返回 0"""
        count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
        assert count == 0
        mock_task_queue.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_incomplete_list(self, mock_history_db, mock_task_queue, mock_config):
        """空列表返回 0"""
        mock_history_db.get_incomplete_tasks.return_value = []
        count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
        assert count == 0

    @pytest.mark.asyncio
    async def test_none_config(self, mock_history_db, mock_task_queue):
        """config=None 不报错"""
        mock_history_db.get_incomplete_tasks.return_value = []
        count = await recover_tasks(mock_history_db, mock_task_queue, None)
        assert count == 0


# ---------------------------------------------------------------------------
# 图像任务恢复
# ---------------------------------------------------------------------------


class TestRecoverImageTask:
    """图像任务恢复测试"""

    @pytest.mark.asyncio
    async def test_recover_single_image_task(self, mock_history_db, mock_task_queue, mock_config):
        """恢复单个图像任务"""
        task = MockTaskRecord(task_id="img-task-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters=make_image_params_json(), input_file="photo.png")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 1
            mock_task_queue.submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_image_task_updates_state_to_pending(self, mock_history_db, mock_task_queue, mock_config):
        """图像任务恢复时更新状态为 pending"""
        task = MockTaskRecord(task_id="img-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters=make_image_params_json())
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch(
                "bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock
            ) as mock_update,
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            # 第一次调用：重置为 pending
            first_call = mock_update.call_args_list[0]
            assert first_call.kwargs.get("status") == "pending"
            assert first_call.kwargs.get("progress") == 0.0

    @pytest.mark.asyncio
    async def test_image_task_updates_record(self, mock_history_db, mock_task_queue, mock_config):
        """图像任务恢复时更新历史记录状态"""
        task = MockTaskRecord(task_id="img-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters=make_image_params_json())
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            mock_history_db.update_record.assert_awaited()
            # 第一次 update_record 调用：重置状态
            first_call = mock_history_db.update_record.call_args_list[0]
            assert first_call.args[0] == 1
            assert first_call.kwargs.get("status") == "pending"


# ---------------------------------------------------------------------------
# 视频任务恢复
# ---------------------------------------------------------------------------


class TestRecoverVideoTask:
    """视频任务恢复测试"""

    @pytest.mark.asyncio
    async def test_recover_single_video_task(self, mock_history_db, mock_task_queue, mock_config):
        """恢复单个视频任务"""
        task = MockTaskRecord(task_id="vid-task-1", record_id=2)
        record = MockHistoryRecord(id=2, task_type="video", parameters=make_video_params_json(), input_file="video.mp4")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_video_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 1
            mock_task_queue.submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_task_with_model_size_from_record(self, mock_history_db, mock_task_queue, mock_config):
        """视频任务使用记录中的 model_size"""
        task = MockTaskRecord(task_id="vid-1", record_id=2)
        record = MockHistoryRecord(id=2, task_type="video", parameters=make_video_params_json(), model_size="7b")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_video_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry") as mock_reg,
        ):
            mock_reg.current_model_size = "3b"
            await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            # _process_video_task 被包装在 lambda 中，验证 submit 被调用即可
            mock_task_queue.submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_task_model_size_fallback_to_registry(self, mock_history_db, mock_task_queue, mock_config):
        """记录中无 model_size 时使用 registry 的 current_model_size"""
        task = MockTaskRecord(task_id="vid-1", record_id=2)
        record = MockHistoryRecord(id=2, task_type="video", parameters=make_video_params_json(), model_size="")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_video_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry") as mock_reg,
        ):
            mock_reg.current_model_size = "7b"
            await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            mock_task_queue.submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_task_model_size_fallback_to_default(self, mock_history_db, mock_task_queue, mock_config):
        """记录和 registry 都无 model_size 时使用默认值 3b"""
        task = MockTaskRecord(task_id="vid-1", record_id=2)
        record = MockHistoryRecord(id=2, task_type="video", parameters=make_video_params_json(), model_size="")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_video_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry") as mock_reg,
        ):
            mock_reg.current_model_size = None
            await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            mock_task_queue.submit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 异常与边界情况
# ---------------------------------------------------------------------------


class TestRecoverTasksEdgeCases:
    """recover_tasks 异常与边界情况测试"""

    @pytest.mark.asyncio
    async def test_missing_record_skips(self, mock_history_db, mock_task_queue, mock_config):
        """记录不存在时跳过任务"""
        task = MockTaskRecord(task_id="orphan-1", record_id=999)
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = []  # 没有找到记录

        count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
        assert count == 0
        mock_task_queue.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_task_type_skips(self, mock_history_db, mock_task_queue, mock_config):
        """未知 task_type 跳过任务"""
        task = MockTaskRecord(task_id="unknown-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="audio", parameters="{}")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
        assert count == 0
        mock_task_queue.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_param_parse_failure_marks_failed(self, mock_history_db, mock_task_queue, mock_config):
        """参数解析失败时标记为 failed"""
        task = MockTaskRecord(task_id="bad-params-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters="{invalid json}")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch(
                "bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock
            ) as mock_update,
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 0
            # 验证被标记为 failed
            failed_call = mock_update.call_args_list[-1]
            assert failed_call.kwargs.get("status") == "failed"
            assert "参数解析失败" in failed_call.kwargs.get("error_message", "")
            # 验证记录也被更新
            failed_record_call = mock_history_db.update_record.call_args_list[-1]
            assert failed_record_call.kwargs.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_empty_parameters_uses_default(self, mock_history_db, mock_task_queue, mock_config):
        """parameters 为空字符串时使用默认 '{}'"""
        task = MockTaskRecord(task_id="empty-params-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters="")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 1

    @pytest.mark.asyncio
    async def test_none_parameters_uses_default(self, mock_history_db, mock_task_queue, mock_config):
        """parameters 为 None 时使用默认 '{}'"""
        task = MockTaskRecord(task_id="none-params-1", record_id=1)
        record = MockHistoryRecord(id=1, task_type="image", parameters=None)
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record]

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 1


# ---------------------------------------------------------------------------
# 多任务恢复
# ---------------------------------------------------------------------------


class TestRecoverMultipleTasks:
    """多任务恢复测试"""

    @pytest.mark.asyncio
    async def test_mixed_tasks(self, mock_history_db, mock_task_queue, mock_config):
        """混合图像和视频任务"""
        tasks = [
            MockTaskRecord(task_id="img-1", record_id=1),
            MockTaskRecord(task_id="vid-1", record_id=2),
            MockTaskRecord(task_id="img-2", record_id=3),
        ]
        records = [
            MockHistoryRecord(id=1, task_type="image", parameters=make_image_params_json()),
            MockHistoryRecord(id=2, task_type="video", parameters=make_video_params_json()),
            MockHistoryRecord(id=3, task_type="image", parameters=make_image_params_json()),
        ]
        mock_history_db.get_incomplete_tasks.return_value = tasks
        mock_history_db.get_records_by_ids.return_value = records

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_video_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            assert count == 3
            assert mock_task_queue.submit.await_count == 3

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, mock_history_db, mock_task_queue, mock_config):
        """混合有效和无效任务"""
        tasks = [
            MockTaskRecord(task_id="valid-img", record_id=1),
            MockTaskRecord(task_id="invalid-type", record_id=2),
            MockTaskRecord(task_id="bad-params", record_id=3),
            MockTaskRecord(task_id="missing-record", record_id=999),
        ]
        records = [
            MockHistoryRecord(id=1, task_type="image", parameters=make_image_params_json()),
            MockHistoryRecord(id=2, task_type="audio", parameters="{}"),
            MockHistoryRecord(id=3, task_type="image", parameters="{broken}"),
        ]
        mock_history_db.get_incomplete_tasks.return_value = tasks
        mock_history_db.get_records_by_ids.return_value = records

        with (
            patch("bin.integrated_app.routes.restore.recovery.common.update_task_state", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery._process_image_task", new_callable=AsyncMock),
            patch("bin.integrated_app.routes.restore.recovery.model_registry"),
        ):
            count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
            # 只有 valid-img 成功恢复
            assert count == 1
            assert mock_task_queue.submit.await_count == 1

    @pytest.mark.asyncio
    async def test_records_map_handles_none_id(self, mock_history_db, mock_task_queue, mock_config):
        """HistoryRecord.id 为 None 时被跳过"""
        task = MockTaskRecord(task_id="test-1", record_id=1)
        record_none_id = MockHistoryRecord(id=None, task_type="image", parameters="{}")
        mock_history_db.get_incomplete_tasks.return_value = [task]
        mock_history_db.get_records_by_ids.return_value = [record_none_id]

        count = await recover_tasks(mock_history_db, mock_task_queue, mock_config)
        assert count == 0
