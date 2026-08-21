from unittest import mock

from launcher.dependency_check import (
    TORCH_INDEXES,
    TorchCheckResult,
    check_torch,
    torch_install_cmd,
)


def test_torch_indexes_known():
    assert "pytorch-cu128" in TORCH_INDEXES
    assert "aliyun-cu128" in TORCH_INDEXES


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


def test_torch_install_cmd_uses_index():
    cmd = torch_install_cmd("C:/py/python.exe", "pytorch-cu128")
    assert "--index-url https://download.pytorch.org/whl/cu128" in " ".join(cmd)
    assert "torch" in cmd and "torchvision" in cmd and "torchaudio" in cmd
