from unittest import mock

from launcher.dependency_check import (
    TORCH_CUDA_VERSIONS,
    TORCH_INDEXES,
    TorchCheckResult,
    check_torch,
    recommend_cuda_index,
    torch_install_cmd,
    _parse_cuda_from_driver,
)


def test_torch_indexes_known():
    assert "pytorch-cu128" in TORCH_INDEXES
    assert "aliyun-cu128" in TORCH_INDEXES
    # 官方源走 index-url，国内镜像走 find-links
    assert TORCH_INDEXES["pytorch-cu128"]["index"] is not None
    assert TORCH_INDEXES["aliyun-cu128"]["find_links"] is not None


def test_torch_indexes_have_cuda_and_label():
    for cfg in TORCH_INDEXES.values():
        assert cfg["cuda"], cfg
        assert cfg["label"]


def test_parse_cuda_from_driver_ranges():
    assert _parse_cuda_from_driver("13.3") == "cu128"
    assert _parse_cuda_from_driver("12.8") == "cu128"
    assert _parse_cuda_from_driver("12.6") == "cu126"
    assert _parse_cuda_from_driver("12.4") == "cu121"
    assert _parse_cuda_from_driver("12.1") == "cu121"
    assert _parse_cuda_from_driver("11.8") == "cu118"
    assert _parse_cuda_from_driver(None) == "cu128"
    assert _parse_cuda_from_driver("") == "cu128"


def test_recommend_cuda_index():
    assert recommend_cuda_index("13.3") == "aliyun-cu128"
    assert recommend_cuda_index("11.8") == "aliyun-cu118"


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_all_installed(mock_run):
    mock_run.return_value = (
        0,
        '{"torch": "2.7.1+cu128", "torchvision": "0.22.1+cu128", "torchaudio": "2.7.1+cu128"}',
    )
    res = check_torch("C:/py/python.exe")
    assert res.installed is True
    assert res.versions["torch"] == "2.7.1+cu128"


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_missing(mock_run):
    mock_run.return_value = (
        0,
        '{"torch": null, "torchvision": null, "torchaudio": null}',
    )
    res = check_torch("C:/py/python.exe")
    assert res.installed is False


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_cuda_available(mock_run):
    def fake(py, code):
        if "cuda.is_available" in code:
            return 0, "True"
        return 0, '{"torch": "2.7.1+cu128", "torchvision": "0.22.1+cu128", "torchaudio": "2.7.1+cu128"}'

    mock_run.side_effect = fake
    res = check_torch("C:/py/python.exe")
    assert res.cuda_available is True


def test_torch_install_cmd_official_uses_index_url():
    cmd = torch_install_cmd("C:/py/python.exe", "pytorch-cu128")
    joined = " ".join(cmd)
    assert "--index-url https://download.pytorch.org/whl/cu128" in joined
    # 官方源应带 CUDA 版本约束，而非裸包名
    assert "torch==2.11.0+cu128" in cmd
    assert all(p in cmd for p in ["torchvision==0.28.0+cu128", "torchaudio==2.11.0+cu128"])


def test_torch_install_cmd_aliyun_uses_find_links():
    cmd = torch_install_cmd("C:/py/python.exe", "aliyun-cu128")
    joined = " ".join(cmd)
    assert "--find-links https://mirrors.aliyun.com/pytorch-wheels/cu128" in joined
    assert "--index-url" not in joined
    assert "torch==2.11.0+cu128" in cmd


def test_torch_install_cmd_alias_is_default():
    # 默认（未传 index_key）仍走官方 cu128
    cmd = torch_install_cmd("C:/py/python.exe")
    assert "torch==2.11.0+cu128" in cmd
