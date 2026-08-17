"""FastAPI 接口基础测试

覆盖范围：
- 首页加载
- 历史记录 API（列表 / HTMX 片段 / 分页边界）
- 统一修复页面与扫描白名单
- 系统健康检查 / GPU / 指标 / 设置 / 语言 / 模型管理
- 修复任务进度 SSE / 结果 / 下载
- 统一响应结构校验 {success, data, error}
"""

import io
import pytest

from tests.conftest import csrf_post

pytestmark = pytest.mark.integration


class TestIndexPage:
    """首页测试"""

    def test_index_returns_200_and_contains_seedvr2(self, test_app):
        response = test_app.get("/")
        assert response.status_code == 200
        assert "SeedVR2" in response.text


class TestHistoryAPI:
    """历史记录 API 测试"""

    def test_history_returns_json(self, test_app):
        response = test_app.get("/api/system/history")
        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert isinstance(data["records"], list)

    def test_history_table_htmx_returns_html_fragment(self, test_app):
        response = test_app.get(
            "/api/system/history/table",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        # HTML 片段不应包含完整页面包装
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text
        assert "<body" not in response.text
        assert "<table" not in response.text
        assert "<tbody" not in response.text

    def test_history_pagination_page_zero_returns_422(self, test_app):
        """分页边界：page=0 应返回 422（page 最小值为 1）"""
        response = test_app.get("/api/system/history?page=0&page_size=10")
        assert response.status_code == 422

    def test_history_pagination_large_page(self, test_app):
        """分页边界：page 远超总页数应返回空列表"""
        response = test_app.get("/api/system/history?page=9999&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["records"] == []

    def test_history_pagination_max_page_size(self, test_app):
        """分页边界：page_size=100（最大值）应返回有效响应"""
        response = test_app.get("/api/system/history?page=1&page_size=100")
        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 100
        assert isinstance(data["records"], list)

    def test_history_pagination_oversize_page_size_returns_422(self, test_app):
        """分页边界：page_size=1000 超过最大值 100，应返回 422"""
        response = test_app.get("/api/system/history?page=1&page_size=1000")
        assert response.status_code == 422


class TestUnifiedRestoreAPI:
    """统一修复页面与 API 测试"""

    def test_restore_page_returns_200(self, test_app):
        response = test_app.get("/restore")
        assert response.status_code == 200
        assert "SeedVR2" in response.text
        # 统一页面应包含任务类型选择或上传区域标识
        assert "restoreUploadZone" in response.text

    def test_scan_folder_outside_whitelist_returns_403(self, test_app):
        """SECURITY [D4-1]: 白名单外的路径应返回 403，不泄露路径是否存在"""
        response = test_app.get("/api/restore/scan-folder?folder_path=/definitely/not/exists")
        assert response.status_code == 403

    def test_scan_folder_not_found_in_whitelist_returns_404(self, test_app):
        """白名单内但不存在的路径应返回 404"""
        # outputs/ 在默认白名单内，但其下不存在的子路径应返回 404
        response = test_app.get("/api/restore/scan-folder?folder_path=outputs/definitely_not_exists_subdir")
        assert response.status_code == 404

    def test_restore_without_input_returns_400(self, test_app):
        """POST /api/restore/ 空输入应返回 400"""
        response = csrf_post(test_app, "/api/restore/", data={})
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_restore_without_model_returns_503(self, test_app):
        """模型未加载时 POST /api/restore/ 应返回 503"""
        # 提供一个有效的图片文件名但无文件内容 — 应因 GPU/模型不可用返回 503
        response = csrf_post(
            test_app,
            "/api/restore/",
            data={
                "task_type": "image",
                "dit_model": "3b_fp16",
            },
            files={"file": ("test.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
        )
        assert response.status_code == 503


class TestHealthAPI:
    """系统健康检查 API 测试"""

    def test_ping_returns_ok(self, test_app):
        """GET /api/system/ping 应返回 {status, version, gpu_available}"""
        response = test_app.get("/api/system/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "gpu_available" in data
        assert isinstance(data["gpu_available"], bool)

    def test_health_returns_detailed_info(self, test_app):
        """GET /api/system/health 应返回 {status, uptime_seconds, system, model, gpu}"""
        response = test_app.get("/api/system/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert "system" in data
        assert "platform" in data["system"]
        assert "python_version" in data["system"]
        assert "cpu_count" in data["system"]
        assert "memory_total_gb" in data["system"]
        assert "memory_available_gb" in data["system"]
        assert "memory_utilization_pct" in data["system"]
        assert "model" in data
        assert "gpu" in data
        assert "backend" in data["gpu"]
        assert "device_name" in data["gpu"]
        assert "is_gpu_available" in data["gpu"]


class TestSettingsAPI:
    """系统设置 API 测试"""

    def test_get_settings_returns_config(self, test_app):
        """GET /api/system/settings 应返回 {model, gpu, i18n, restore, user_preferences}"""
        response = test_app.get("/api/system/settings")
        assert response.status_code == 200
        data = response.json()
        assert "model" in data
        assert "gpu" in data
        assert "i18n" in data
        assert "restore" in data
        assert "user_preferences" in data

    def test_update_settings_round_trip(self, test_app):
        """POST /api/system/settings 写入后再读取应一致"""
        response = csrf_post(
            test_app,
            "/api/system/settings",
            json={"default_model_size": "7b", "default_precision": "fp16"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        # 读取验证
        get_response = test_app.get("/api/system/settings")
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert get_data["model"]["default_size"] == "7b"
        assert get_data["model"]["default_precision"] == "fp16"


class TestModelAPI:
    """模型管理 API 测试"""

    def test_model_status_returns_state(self, test_app):
        """GET /api/system/model/status 应返回模型状态"""
        response = test_app.get("/api/system/model/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "loaded" in data

    def test_model_load_with_mock(self, test_app):
        """POST /api/system/model/load 应通过 mock manager 加载模型"""
        response = csrf_post(
            test_app,
            "/api/system/model/load",
            json={"size": "3b"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    def test_model_unload_with_mock(self, test_app):
        """POST /api/system/model/unload 应通过 mock manager 卸载模型"""
        response = csrf_post(test_app, "/api/system/model/unload", json={})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


class TestLocalesAPI:
    """多语言 API 测试"""

    def test_get_locales_returns_list(self, test_app):
        """GET /api/system/locales 应返回 {current, locales[]}"""
        response = test_app.get("/api/system/locales")
        assert response.status_code == 200
        data = response.json()
        assert "current" in data
        assert "locales" in data
        assert isinstance(data["locales"], list)
        assert len(data["locales"]) > 0
        # 每个条目应有 code 和 name
        for locale in data["locales"]:
            assert "code" in locale
            assert "name" in locale

    def test_set_locale_to_en(self, test_app):
        """POST /api/system/locale 应切换语言"""
        response = csrf_post(
            test_app,
            "/api/system/locale",
            json={"locale": "en"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["locale"] == "en"
        assert "message" in data


class TestMetricsAPI:
    """性能指标 API 测试"""

    def test_get_metrics_returns_snapshot(self, test_app):
        """GET /api/system/metrics 应返回指标快照"""
        response = test_app.get("/api/system/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert isinstance(data["data"], dict)

    def test_get_inference_history_returns_list(self, test_app):
        """GET /api/system/metrics/inference 应返回推理历史列表"""
        response = test_app.get("/api/system/metrics/inference")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)


class TestGPUAPI:
    """GPU 信息 API 测试"""

    def test_get_gpu_info(self, test_app):
        """GET /api/system/gpu 应返回 GPU 信息"""
        response = test_app.get("/api/system/gpu")
        assert response.status_code == 200
        data = response.json()
        assert "backend" in data
        assert "device_name" in data
        assert "vram_total_mb" in data
        assert "vram_available_mb" in data
        assert "utilization_pct" in data
        assert "cuda_version" in data
        assert "driver_version" in data
        assert "memory" in data

    def test_get_gpu_system_info(self, test_app):
        """GET /api/system/gpu/system 应返回完整系统信息"""
        response = test_app.get("/api/system/gpu/system")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestRestoreTaskFlow:
    """修复任务流接口测试（进度 / 结果 / 下载）

    使用不存在的 task_id 测试 404 路径，验证 API 契约完整性。
    """

    def test_progress_nonexistent_task_returns_404(self, test_app):
        """GET /api/restore/{task_id}/progress 对不存在的任务应返回 404"""
        response = test_app.get("/api/restore/nonexistent_task_001/progress")
        assert response.status_code == 404

    def test_result_nonexistent_task_returns_404(self, test_app):
        """GET /api/restore/{task_id}/result 对不存在的任务应返回 404"""
        response = test_app.get("/api/restore/nonexistent_task_001/result")
        assert response.status_code == 404

    def test_download_nonexistent_task_returns_404(self, test_app):
        """GET /api/restore/{task_id}/download 对不存在的任务应返回 404"""
        response = test_app.get("/api/restore/nonexistent_task_001/download")
        assert response.status_code == 404

    def test_cancel_nonexistent_task_returns_404(self, test_app):
        """POST /api/restore/{task_id}/cancel 对不存在的任务应返回 404"""
        response = csrf_post(test_app, "/api/restore/nonexistent_task_001/cancel", json={})
        assert response.status_code == 404

    def test_batch_progress_nonexistent_returns_404(self, test_app):
        """GET /api/restore/batch/{batch_id}/progress 对不存在的批次应返回 404"""
        response = test_app.get("/api/restore/batch/nonexistent_batch_001/progress")
        assert response.status_code == 404
