# tests/test_launcher_model_check.py
from pathlib import Path

from launcher.model_check import (
    MAIN_MODEL_FILES,
    MANDATORY_FILES,
    ModelCheckResult,
    check_models,
    recommend_main_model,
)


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_mandatory_and_main_lists():
    assert set(MANDATORY_FILES) == {"ema_vae_fp16.safetensors", "pos_emb.pt", "neg_emb.pt"}
    assert len(MAIN_MODEL_FILES) == 6


def test_check_models_missing_all(tmp_path: Path):
    res = check_models(tmp_path)
    assert res.mandatory_ok is False
    assert res.main_model_ok is False
    assert res.ready is False


def test_check_models_mandatory_only(tmp_path: Path):
    for name in MANDATORY_FILES:
        data = b"<safetensors>" + b"\x00" * 16 if name.endswith(".safetensors") else b"x" * 10
        _write_bytes(tmp_path / name, data)
    res = check_models(tmp_path)
    assert res.mandatory_ok is True
    assert res.main_model_ok is False
    assert res.ready is False


def test_check_models_all_ok(tmp_path: Path):
    for name in MANDATORY_FILES:
        data = b"<safetensors>" + b"\x00" * 16 if name.endswith(".safetensors") else b"x" * 10
        _write_bytes(tmp_path / name, data)
    _write_bytes(tmp_path / MAIN_MODEL_FILES[0], b"<safetensors>" + b"\x00" * 16)
    res = check_models(tmp_path)
    assert res.ready is True
    assert res.files[MAIN_MODEL_FILES[0]]["ok"] is True


def test_check_models_safetensors_bad_magic(tmp_path: Path):
    for name in MANDATORY_FILES:
        _write_bytes(tmp_path / name, b"x" * 10)
    _write_bytes(tmp_path / MAIN_MODEL_FILES[0], b"NOT_SAFETENSORS" + b"\x00" * 16)
    res = check_models(tmp_path)
    assert res.ready is False
    assert res.files[MAIN_MODEL_FILES[0]]["ok"] is False


def test_recommend_by_vram():
    assert recommend_main_model(8) == "3b_fp8"
    assert recommend_main_model(16) == "3b_fp16"
    assert recommend_main_model(30) == "7b_sharp_fp16"
