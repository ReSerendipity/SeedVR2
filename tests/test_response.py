"""测试统一响应包装工具

REFACTOR: 覆盖 respond_success / respond_error 的结构、字段、
         状态码、空 data、extra 透传等语义，确保前端契约稳定。
"""

from __future__ import annotations

import json

from fastapi.responses import JSONResponse

from bin.integrated_app.utils.response import respond_error, respond_success


class TestRespondSuccess:
    """成功响应包装"""

    def test_basic_success(self):
        resp = respond_success(data={"foo": "bar"})
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["success"] is True
        assert body["data"] == {"foo": "bar"}

    def test_default_status_200(self):
        resp = respond_success(data=None)
        assert resp.status_code == 200

    def test_custom_status(self):
        resp = respond_success(data={"id": 1}, status=201)
        assert resp.status_code == 201

    def test_none_data_omitted(self):
        """data=None 时 body 中不应包含 data 字段"""
        resp = respond_success(data=None)
        body = json.loads(resp.body)
        assert "data" not in body
        assert body["success"] is True

    def test_extra_fields_merged_at_top_level(self):
        """**extra 透传到顶层"""
        resp = respond_success(
            data={"file": "x.png"},
            message="ok",
            task_id="t-123",
        )
        body = json.loads(resp.body)
        assert body["success"] is True
        assert body["data"] == {"file": "x.png"}
        assert body["message"] == "ok"
        assert body["task_id"] == "t-123"

    def test_empty_data_string_preserved(self):
        """空字符串是有效数据，应保留"""
        resp = respond_success(data="")
        body = json.loads(resp.body)
        assert body["data"] == ""

    def test_falsy_data_preserved(self):
        """0/False/[] 等 falsy 值应保留（仅 None 被省略）"""
        for falsy in [0, False, [], {}]:
            resp = respond_success(data=falsy)
            body = json.loads(resp.body)
            assert body["data"] == falsy


class TestRespondError:
    """错误响应包装"""

    def test_basic_error(self):
        resp = respond_error(code="PATH_NOT_ALLOWED", message="不允许访问该路径")
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 400
        body = json.loads(resp.body)
        assert body["success"] is False
        assert body["error"]["code"] == "PATH_NOT_ALLOWED"
        assert body["error"]["message"] == "不允许访问该路径"
        assert body["error"]["detail"] == {}

    def test_custom_status(self):
        resp = respond_error(code="NOT_FOUND", message="不存在", status=404)
        assert resp.status_code == 404

    def test_detail_provided(self):
        resp = respond_error(
            code="VALIDATION_ERROR",
            message="参数错误",
            status=422,
            detail={"field": "size", "reason": "must be positive"},
        )
        body = json.loads(resp.body)
        assert body["error"]["detail"] == {"field": "size", "reason": "must be positive"}

    def test_detail_none_defaults_to_empty_dict(self):
        resp = respond_error(code="X", message="y", detail=None)
        body = json.loads(resp.body)
        assert body["error"]["detail"] == {}

    def test_no_data_field_in_error(self):
        """错误响应不应包含 data 字段"""
        resp = respond_error(code="X", message="y")
        body = json.loads(resp.body)
        assert "data" not in body

    def test_error_structure_keys(self):
        """error 字典必须且仅有 code/message/detail 三个键"""
        resp = respond_error(code="X", message="y", detail={"k": "v"})
        body = json.loads(resp.body)
        assert set(body["error"].keys()) == {"code", "message", "detail"}


class TestResponseConsistency:
    """前端契约一致性"""

    def test_success_and_error_share_success_flag(self):
        ok = respond_success(data=1)
        err = respond_error(code="X", message="y")
        ok_body = json.loads(ok.body)
        err_body = json.loads(err.body)
        assert ok_body["success"] is True
        assert err_body["success"] is False
        # 成功响应不应有 error 字段
        assert "error" not in ok_body
        # 错误响应不应有 data 字段
        assert "data" not in err_body

    def test_content_type_is_json(self):
        resp = respond_success(data=1)
        assert resp.media_type == "application/json"

    def test_serializable_body(self):
        """body 必须是合法 JSON bytes"""
        resp = respond_success(data={"k": "v"})
        assert isinstance(resp.body, bytes)
        # 不抛异常即通过
        json.loads(resp.body)
