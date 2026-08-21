# tests/test_launcher_setup_state.py
import json
from pathlib import Path

from launcher.setup_state import SetupState, DEFAULT_STATE


def test_default_state_when_no_file(tmp_path: Path):
    s = SetupState(tmp_path / ".setup_state.json")
    assert s.get("torch_installed") is False
    assert s.get("torch_verified") is False


def test_set_persists_to_disk(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    s = SetupState(f)
    s.set("torch_installed", True)
    s.set("torch_verified", True)
    loaded = json.loads(f.read_text(encoding="utf-8"))
    assert loaded["torch_installed"] is True
    assert loaded["torch_verified"] is True


def test_reload_resumes_existing_state(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    f.write_text(json.dumps({"torch_installed": True, "torch_verified": True}), encoding="utf-8")
    s = SetupState(f)
    assert s.torch_ready is True


def test_corrupted_file_falls_back_to_default(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    f.write_text("{not json", encoding="utf-8")
    s = SetupState(f)
    assert s.get("torch_installed") is False


def test_save_is_atomic_no_tmp_left(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    s = SetupState(f)
    s.set("smoke_test_passed", True)
    assert not (tmp_path / ".setup_state.json.tmp").exists()
