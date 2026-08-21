# tests/test_launcher_env_check.py
from pathlib import Path
from unittest import mock

from launcher.env_check import (
    MIN_DISK_GB,
    EnvCheckResult,
    check_env,
    _parse_nvidia_smi,
    _parse_nvidia_mem,
    _parse_nvidia_query,
    _check_disk_space,
)


def test_parse_nvidia_smi_detects_gpu():
    out = (
        "NVIDIA-SMI 572.83  Driver Version: 572.83  CUDA Version: 13.3\n"
        "|  NVIDIA GeForce RTX 3060                 ...\n"
    )
    res = _parse_nvidia_smi(out)
    assert res["gpu_found"] is True
    assert res["gpu_name"] == "NVIDIA GeForce RTX 3060"
    assert res["driver_version"] == "572.83"
    assert res["cuda_version"] == "13.3"


def test_parse_nvidia_smi_kmt_umd_format():
    # 新版驱动（610.xx）使用 "KMD Version" + "CUDA UMD Version" 头
    out = (
        "NVIDIA-SMI 610.88  KMD Version: 610.88  CUDA UMD Version: 13.3\n"
        "|   0  NVIDIA GeForce RTX 5070 Ti Laptop GPU ...\n"
    )
    res = _parse_nvidia_smi(out)
    assert res["driver_version"] == "610.88"
    assert res["cuda_version"] == "13.3"


def test_parse_nvidia_query_name_and_vram():
    name, vram = _parse_nvidia_query("NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12227 MiB")
    assert name == "NVIDIA GeForce RTX 5070 Ti Laptop GPU"
    assert vram == 11.9


def test_parse_nvidia_query_empty():
    assert _parse_nvidia_query("") == (None, None)


def test_parse_nvidia_smi_no_gpu():
    res = _parse_nvidia_smi("NVIDIA-SMI has failed because it couldn't communicate")
    assert res["gpu_found"] is False
    assert res["gpu_name"] is None


@mock.patch("launcher.env_check.shutil.disk_usage")
def test_disk_check_enough(mock_usage):
    # 2 TB total / 500 GB free
    mock_usage.return_value = (2 * 1024**4, 500 * 1024**3, 1 * 1024**4)
    assert _check_disk_space(Path("C:/")) is True


@mock.patch("launcher.env_check.shutil.disk_usage")
def test_disk_check_insufficient(mock_usage):
    # 100 GB total / 5 GB free
    mock_usage.return_value = (100 * 1024**3, 95 * 1024**3, 5 * 1024**3)
    assert _check_disk_space(Path("C:/")) is False


@mock.patch("launcher.env_check._run_nvidia_smi")
@mock.patch("launcher.env_check._run_nvidia_mem")
@mock.patch("launcher.env_check._check_disk_space")
def test_check_env_aggregates(mock_disk, mock_mem, mock_smi):
    mock_smi.return_value = (
        "NVIDIA-SMI 572.83  Driver Version: 572.83  CUDA Version: 13.3\n"
        "|  NVIDIA GeForce RTX 3060\n"
    )
    mock_mem.return_value = "NVIDIA GeForce RTX 3060, 12288 MiB"
    mock_disk.return_value = True
    res = check_env(Path("C:/SeedVR2-lite"))
    assert isinstance(res, EnvCheckResult)
    assert res.gpu_found is True
    assert res.disk_ok is True
    assert res.disk_free_gb > MIN_DISK_GB
    assert res.vram_gb == 12.0


@mock.patch("launcher.env_check._run_nvidia_mem")
def test_parse_nvidia_mem_vram(mock_mem):
    mock_mem.return_value = "NVIDIA GeForce RTX 4090, 24564 MiB"
    assert _parse_nvidia_mem(mock_mem.return_value) == 24.0
