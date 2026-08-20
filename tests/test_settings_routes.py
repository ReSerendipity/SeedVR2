"""系统设置路由测试 (routes/system/settings.py) — browse-dir / validate_path / open-explorer。"""

import pytest
from fastapi import HTTPException

from app.integrated_app.routes.system.settings import validate_path

pytestmark = pytest.mark.integration

# ---------- validate_path ----------


def test_validate_path_empty():
    with pytest.raises(HTTPException) as e:
        validate_path("")
    assert e.value.status_code == 400


def test_validate_path_dotdot():
    with pytest.raises(HTTPException) as e:
        validate_path("../etc/passwd")
    assert e.value.status_code == 400


def test_validate_path_outside_allowed_roots(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(HTTPException) as e:
        validate_path(str(outside), allowed_roots=[str(tmp_path / "allowed")])
    assert e.value.status_code == 403


def test_validate_path_inside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sub = allowed / "sub"
    sub.mkdir()
    resolved = validate_path(str(sub), allowed_roots=[str(allowed)])
    assert resolved == str(sub.resolve())


def test_validate_path_no_roots_ok(tmp_path):
    sub = tmp_path / "x"
    sub.mkdir()
    assert validate_path(str(sub), allowed_roots=[]) == str(sub.resolve())


# ---------- browse_directory ----------


def test_browse_directory_empty_returns_drives(test_app):
    resp = test_app.get("/api/system/browse-dir")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == ""
    assert "items" in data
    assert len(data["items"]) >= 1
    assert data["items"][0]["type"] == "drive"


def test_browse_directory_lists_dir(test_app, tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    f = tmp_path / "note.txt"
    f.write_text("hi")
    resp = test_app.get("/api/system/browse-dir", params={"path": str(tmp_path)})
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {i["name"] for i in items}
    assert "subdir" in names
    # show_files=False 时不返回文件
    assert "note.txt" not in names


def test_browse_directory_show_files(test_app, tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 10)
    resp = test_app.get("/api/system/browse-dir", params={"path": str(tmp_path), "show_files": True})
    assert resp.status_code == 200
    files = [i for i in resp.json()["items"] if i["type"] == "file"]
    assert any(i["name"] == "data.bin" and i.get("size") == 10 for i in files)


def test_browse_directory_not_found(test_app):
    resp = test_app.get("/api/system/browse-dir", params={"path": "C:/definitely_missing_dir_xyz"})
    assert resp.status_code == 404


def test_browse_directory_not_a_dir(test_app, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    resp = test_app.get("/api/system/browse-dir", params={"path": str(f)})
    assert resp.status_code == 400


def test_browse_directory_dotdot_rejected(test_app):
    resp = test_app.get("/api/system/browse-dir", params={"path": "../../"})
    assert resp.status_code == 400


def test_browse_directory_parent_path(test_app, tmp_path):
    sub = tmp_path / "child"
    sub.mkdir()
    resp = test_app.get("/api/system/browse-dir", params={"path": str(sub)})
    assert resp.status_code == 200
    parent = resp.json()["parent_path"]
    assert parent == str(tmp_path.resolve())


# ---------- open-explorer ----------


def _csrf_post(client, url, **kwargs):
    """带 CSRF token 的 POST（与 conftest.csrf_post 逻辑一致）。"""
    client.get("/")
    token = client.cookies.get("csrf_token")
    headers = kwargs.pop("headers", {})
    if token:
        headers["X-CSRF-Token"] = token
    return client.post(url, headers=headers, **kwargs)


def test_open_explorer_invalid_path(test_app):
    # 空路径 -> 400
    resp = _csrf_post(test_app, "/api/system/open-explorer", json={"path": "  "})
    assert resp.status_code == 400
    # 含 .. -> 400 或 403（取决于 realpath 顺序）
    resp2 = _csrf_post(test_app, "/api/system/open-explorer", json={"path": "..."})
    assert resp2.status_code in (400, 403)


def test_open_explorer_valid_path(test_app, tmp_path):
    import sys

    import app.integrated_app.routes.system.settings as sm

    if sys.platform == "win32":
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(sm.os, "startfile") as mock_sf:
            resp = _csrf_post(test_app, "/api/system/open-explorer", json={"path": str(tmp_path)})
        assert mock_sf.called
    else:
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(sm.subprocess, "Popen") as mock_popen:
            resp = _csrf_post(test_app, "/api/system/open-explorer", json={"path": str(tmp_path)})
        assert mock_popen.called
    assert resp.status_code == 200
