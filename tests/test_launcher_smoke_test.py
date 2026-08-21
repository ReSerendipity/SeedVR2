# tests/test_launcher_smoke_test.py
import json
from unittest import mock

from launcher.smoke_test import (
    SmokeTestResult,
    build_multipart,
    poll_until_done,
    run_smoke_test,
)


def test_build_multipart_contains_file():
    body, content_type = build_multipart(
        filename="a.jpg", filedata=b"\xff\xd8\xff", extra_fields={"dit_model": "3b_fp16"}
    )
    assert b'name="file"' in body
    assert b'filename="a.jpg"' in body
    assert b'name="dit_model"' in body
    assert "multipart/form-data; boundary=" in content_type


class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class _FakeUrlopen:
    def __init__(self, plan):
        self._plan = list(plan)

    def __call__(self, req, data=None, timeout=None):
        # 顺序返回预先排好的响应
        return self._plan.pop(0)


def test_run_smoke_test_success():
    plan = [
        # 健康检查
        _FakeResp(200, {"success": True}),
        # 上传
        _FakeResp(200, {"success": True, "data": {"task_id": "abc123"}}),
        # progress -> processing
        _FakeResp(200, {"success": True, "data": {"status": "processing", "progress": 50}}),
        # result -> completed
        _FakeResp(
            200,
            {"success": True, "data": {"status": "completed", "output_path": "C:/out/ok.png", "file_size": 123}},
        ),
    ]
    fake = _FakeUrlopen(plan)
    with mock.patch("launcher.smoke_test.urlopen", fake), \
         mock.patch("launcher.smoke_test.time.sleep", return_value=None):
        res = run_smoke_test(
            app_base_url="http://127.0.0.1:7870",
            test_image=__file__,
        )
    assert isinstance(res, SmokeTestResult)
    assert res.success is True
    assert res.output_path == "C:/out/ok.png"


def test_poll_until_done_failed_task():
    plan = [
        _FakeResp(200, {"success": True, "data": {"status": "failed", "error": "OOM"}}),
    ]
    fake = _FakeUrlopen(plan)
    with mock.patch("launcher.smoke_test.urlopen", fake), \
         mock.patch("launcher.smoke_test.time.sleep", return_value=None):
        res = poll_until_done("http://127.0.0.1:7870", "abc123", timeout=5)
    assert res.success is False
    assert "OOM" in res.message
