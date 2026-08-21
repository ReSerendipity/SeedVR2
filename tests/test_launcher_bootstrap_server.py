# tests/test_launcher_bootstrap_server.py
import json
from pathlib import Path
from unittest import mock

from launcher.bootstrap_server import Router
from launcher.setup_state import SetupState


def test_router_registers_and_matches(tmp_path: Path):
    r = Router(tmp_path)
    r.get("/api/status", lambda: {"ok": True})
    code, payload, _ = r.dispatch("GET", "/api/status")
    assert code == 200
    assert json.loads(payload)["ok"] is True


def test_router_unknown_404(tmp_path: Path):
    r = Router(tmp_path)
    code, _, _ = r.dispatch("GET", "/api/nope")
    assert code == 404


def test_dispatch_serves_index(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    r = Router(tmp_path)
    code, payload, ctype = r.dispatch("GET", "/")
    assert code == 200
    assert b"<html>hi</html>" in payload
    assert ctype.startswith("text/html")


def test_post_body_parsed_into_last_body(tmp_path: Path):
    r = Router(tmp_path)
    r.post("/api/torch/mirror", lambda: {"index": r._last_body.get("index")})
    code, payload, _ = r.dispatch("POST", "/api/torch/mirror", json.dumps({"index": "aliyun-cu128"}).encode())
    assert json.loads(payload)["index"] == "aliyun-cu128"


@mock.patch("launcher.bootstrap_server.check_models")
def test_api_models_check_uses_model_check(mock_check, tmp_path: Path):
    mock_check.return_value.to_dict.return_value = {
        "ready": True, "files": {}, "mandatory_ok": True, "main_model_ok": True,
    }
    r = Router(tmp_path)
    r.register_api(tmp_path, tmp_path, SetupState(tmp_path / ".setup_state.json"), "C:/py/python.exe")
    code, payload, _ = r.dispatch("GET", "/api/models/check")
    assert code == 200
    mock_check.assert_called_once()
    assert json.loads(payload)["ready"] is True
