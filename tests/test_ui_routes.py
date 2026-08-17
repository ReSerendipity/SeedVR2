"""UI 参数面板与用户偏好 API 路由测试

覆盖 /api/ui/ 下所有端点:
1. GET /api/ui/parameters — 参数定义与预设
2. GET /api/ui/parameters/recommendations — 推荐预设
3. POST /api/ui/parameters/validate — 参数校验
4. GET /api/ui/preferences — 加载用户偏好
5. POST /api/ui/preferences — 保存用户偏好
6. POST /api/ui/preferences/reset — 重置偏好
7. GET /api/ui/layout — 折叠面板布局
"""

import pytest

from tests.conftest import csrf_post

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# 1. 参数定义与预设
# ---------------------------------------------------------------------------


class TestGetParameters:
    """GET /api/ui/parameters 测试"""

    def test_returns_success_and_data(self, test_app):
        response = test_app.get("/api/ui/parameters")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "parameters" in data["data"]
        assert "presets" in data["data"]

    def test_parameters_contain_required_fields(self, test_app):
        response = test_app.get("/api/ui/parameters")
        params = response.json()["data"]["parameters"]
        assert len(params) > 0
        for p in params:
            assert "id" in p
            assert "name" in p
            assert "type" in p
            assert "default" in p
            assert "group" in p

    def test_parameters_include_core_fields(self, test_app):
        """应包含 SeedVR2 核心参数: cfg_scale, denoising_strength, resolution"""
        response = test_app.get("/api/ui/parameters")
        param_ids = {p["id"] for p in response.json()["data"]["parameters"]}
        assert "cfg_scale" in param_ids
        assert "denoising_strength" in param_ids
        assert "resolution" in param_ids

    def test_presets_contain_required_fields(self, test_app):
        response = test_app.get("/api/ui/parameters")
        presets = response.json()["data"]["presets"]
        assert len(presets) > 0
        for preset in presets:
            assert "name" in preset
            assert "description" in preset
            assert "values" in preset
            assert "recommended_ranges" in preset
            assert "use_case" in preset

    def test_presets_contain_three_defaults(self, test_app):
        """应包含三个默认预设: 照片修复, 艺术增强, 轻度去噪"""
        response = test_app.get("/api/ui/parameters")
        preset_names = {p["name"] for p in response.json()["data"]["presets"]}
        assert "照片修复" in preset_names
        assert "艺术增强" in preset_names
        assert "轻度去噪" in preset_names


# ---------------------------------------------------------------------------
# 2. 推荐预设
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    """GET /api/ui/parameters/recommendations 测试"""

    def test_returns_success_and_recommendations(self, test_app):
        response = test_app.get("/api/ui/parameters/recommendations")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "recommendations" in data["data"]

    def test_recommendations_sorted_by_match_score(self, test_app):
        """推荐结果应按匹配度降序排列"""
        response = test_app.get("/api/ui/parameters/recommendations")
        recs = response.json()["data"]["recommendations"]
        scores = [r["match_score"] for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_recommendations_contain_required_fields(self, test_app):
        response = test_app.get("/api/ui/parameters/recommendations")
        recs = response.json()["data"]["recommendations"]
        for rec in recs:
            assert "name" in rec
            assert "description" in rec
            assert "values" in rec
            assert "match_score" in rec

    def test_recommendations_with_custom_params(self, test_app):
        """传入自定义参数应返回匹配结果"""
        response = test_app.get(
            "/api/ui/parameters/recommendations",
            params={"cfg_scale": 3.0, "denoising_strength": 0.6, "steps": 20},
        )
        recs = response.json()["data"]["recommendations"]
        assert len(recs) > 0
        # 照片修复预设 (cfg=3.0, den=0.6) 应有高匹配度
        top = recs[0]
        assert top["match_score"] > 0.5


# ---------------------------------------------------------------------------
# 3. 参数校验
# ---------------------------------------------------------------------------


class TestValidateParameters:
    """POST /api/ui/parameters/validate 测试"""

    def test_valid_values_return_no_errors(self, test_app):
        response = csrf_post(
            test_app,
            "/api/ui/parameters/validate",
            json={"cfg_scale": 3.0, "denoising_strength": 0.6},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["valid"] is True
        assert data["data"]["errors"] == {}

    def test_out_of_range_value_returns_error(self, test_app):
        """超过最大范围的值应返回错误"""
        response = csrf_post(
            test_app,
            "/api/ui/parameters/validate",
            json={"cfg_scale": 100.0},  # max is 10.0
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["valid"] is False
        assert "cfg_scale" in data["data"]["errors"]

    def test_below_min_value_returns_error(self, test_app):
        """低于最小范围的值应返回错误"""
        response = csrf_post(
            test_app,
            "/api/ui/parameters/validate",
            json={"cfg_scale": 0.1},  # min is 1.0
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["valid"] is False
        assert "cfg_scale" in data["data"]["errors"]

    def test_unknown_param_ignored(self, test_app):
        """未知参数应被忽略，不报错"""
        response = csrf_post(
            test_app,
            "/api/ui/parameters/validate",
            json={"unknown_param": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["valid"] is True
        assert data["data"]["errors"] == {}


# ---------------------------------------------------------------------------
# 4. 用户偏好加载
# ---------------------------------------------------------------------------


class TestLoadPreferences:
    """GET /api/ui/preferences 测试"""

    def test_returns_success_and_data(self, test_app):
        response = test_app.get("/api/ui/preferences")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    def test_default_preferences_have_expected_keys(self, test_app):
        """默认偏好应包含核心字段"""
        response = test_app.get("/api/ui/preferences")
        prefs = response.json()["data"]
        assert "default_resolution" in prefs
        assert "default_cfg_scale" in prefs
        assert "default_seed" in prefs
        assert "output_format" in prefs


# ---------------------------------------------------------------------------
# 5. 用户偏好保存
# ---------------------------------------------------------------------------


class TestSavePreferences:
    """POST /api/ui/preferences 测试"""

    def test_save_and_reload(self, test_app):
        """保存偏好后重新加载应返回保存的值"""
        # 保存
        save_resp = csrf_post(
            test_app,
            "/api/ui/preferences",
            json={"default_resolution": 4096, "default_cfg_scale": 5.0},
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["success"] is True

        # 重新加载
        load_resp = test_app.get("/api/ui/preferences")
        prefs = load_resp.json()["data"]
        assert prefs["default_resolution"] == 4096
        assert prefs["default_cfg_scale"] == 5.0

    def test_partial_update_preserves_other_fields(self, test_app):
        """部分更新不应覆盖其他字段"""
        # 先保存一个值
        csrf_post(
            test_app,
            "/api/ui/preferences",
            json={"default_resolution": 4096},
        )
        # 只更新另一个字段
        csrf_post(
            test_app,
            "/api/ui/preferences",
            json={"default_cfg_scale": 7.0},
        )
        # 检查两个字段都保留
        load_resp = test_app.get("/api/ui/preferences")
        prefs = load_resp.json()["data"]
        assert prefs["default_resolution"] == 4096
        assert prefs["default_cfg_scale"] == 7.0


# ---------------------------------------------------------------------------
# 6. 用户偏好重置
# ---------------------------------------------------------------------------


class TestResetPreferences:
    """POST /api/ui/preferences/reset 测试"""

    def test_reset_restores_defaults(self, test_app):
        """重置后应回到默认值"""
        # 先修改
        csrf_post(
            test_app,
            "/api/ui/preferences",
            json={"default_resolution": 9999},
        )
        # 重置
        reset_resp = csrf_post(test_app, "/api/ui/preferences/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["success"] is True

        # 验证恢复默认
        prefs = reset_resp.json()["data"]
        assert prefs["default_resolution"] == 2048  # 默认值


# ---------------------------------------------------------------------------
# 7. 折叠面板布局
# ---------------------------------------------------------------------------


class TestGetLayout:
    """GET /api/ui/layout 测试"""

    def test_returns_success_and_groups(self, test_app):
        response = test_app.get("/api/ui/layout")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "groups" in data["data"]

    def test_groups_contain_required_fields(self, test_app):
        response = test_app.get("/api/ui/layout")
        groups = response.json()["data"]["groups"]
        assert len(groups) > 0
        for g in groups:
            assert "id" in g
            assert "name" in g
            assert "description" in g
            assert "default_expanded" in g
            assert "priority" in g

    def test_groups_sorted_by_priority(self, test_app):
        """分组应按优先级排序"""
        response = test_app.get("/api/ui/layout")
        groups = response.json()["data"]["groups"]
        priorities = [g["priority"] for g in groups]
        assert priorities == sorted(priorities)

    def test_has_three_default_groups(self, test_app):
        """应包含三个默认分组: basic, condition, sampler"""
        response = test_app.get("/api/ui/layout")
        group_ids = {g["id"] for g in response.json()["data"]["groups"]}
        assert "basic" in group_ids
        assert "condition" in group_ids
        assert "sampler" in group_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
