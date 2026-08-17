"""HTMX 历史表格片段测试"""

import pytest

from bin.integrated_app.history_db import HistoryRecord

pytestmark = pytest.mark.integration


class TestHistoryHtmxFragment:
    """HTMX 历史表格局部刷新测试"""

    async def test_empty_table_shows_no_records(self, test_app):
        response = test_app.get(
            "/api/system/history/table",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "sv-empty-state" in response.text
        # 默认语言为 zh-TW（繁体中文），显示"暫無記錄"；zh（简体）显示"暂无记录"
        assert "暫無記錄" in response.text or "暂无记录" in response.text

    async def test_table_contains_record(self, test_app):
        history_db = test_app.app.state.history_db
        record = HistoryRecord(
            task_type="video",
            input_file="C:\\test\\sample_video.mp4",
            output_file="",
            model_size="3b",
            status="completed",
            parameters="{}",
            processing_time=2.5,
            error_message="",
        )
        record_id = await history_db.add_record(record)

        response = test_app.get(
            "/api/system/history/table",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "sample_video.mp4" in response.text
        assert str(record_id) in response.text
        assert "sv-badge-completed" in response.text

    async def test_table_search_filters_records(self, test_app):
        history_db = test_app.app.state.history_db
        record_a = HistoryRecord(
            task_type="video",
            input_file="C:\\test\\alpha_video.mp4",
            output_file="",
            model_size="3b",
            status="completed",
            parameters="{}",
            processing_time=1.0,
            error_message="",
        )
        record_b = HistoryRecord(
            task_type="image",
            input_file="C:\\test\\beta_image.png",
            output_file="",
            model_size="3b",
            status="pending",
            parameters="{}",
            processing_time=0.0,
            error_message="",
        )
        await history_db.add_record(record_a)
        await history_db.add_record(record_b)

        response = test_app.get(
            "/api/system/history/table",
            params={"search": "alpha"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "alpha_video.mp4" in response.text
        assert "beta_image.png" not in response.text

    async def test_table_htmx_header_not_required(self, test_app):
        """表格接口在未携带 HX-Request 时也应返回 HTML 片段"""
        response = test_app.get("/api/system/history/table")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<html" not in response.text
