"""FastAPI 接口基础测试"""

from tests.conftest import csrf_post


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
        # CSRF 保护：POST 请求需携带 CSRF token（通过 csrf_post 自动获取）
        response = csrf_post(test_app, "/api/restore/", data={})
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
