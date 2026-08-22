# tests/test_launcher_python_env.py
from pathlib import Path
from unittest import mock

from launcher.python_env import (
    PyEnv,
    _has_venv_python,
    _system_python,
    _winpython_python,
    chosen_python,
    detect_python_envs,
)
from launcher.setup_state import SetupState


def test_detect_python_envs_venv(tmp_path: Path):
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("x", encoding="utf-8")
    with mock.patch("launcher.python_env._system_python", return_value=None), \
         mock.patch("launcher.python_env._winpython_python", return_value=None), \
         mock.patch("launcher.python_env._python_version", return_value="Python 3.12.0"):
        envs = detect_python_envs(tmp_path, SetupState(tmp_path / ".setup_state.json"))
    assert any(e.id == ".venv" for e in envs)


@mock.patch("launcher.python_env.subprocess.run", return_value=mock.Mock(
    returncode=0, stdout="C:\\Python312\\python.exe\n"))
def test_system_python_found(mock_run):
    root = Path("C:/proj")
    p = _system_python(root)
    assert p is not None
    assert str(p).lower() == "c:\\python312\\python.exe"


@mock.patch("launcher.python_env.subprocess.run", return_value=mock.Mock(
    returncode=0, stdout="C:\\proj\\.venv\\Scripts\\python.exe\n"))
def test_system_python_ignores_own_venv(mock_run):
    assert _system_python(Path("C:/proj")) is None


@mock.patch("launcher.python_env.subprocess.run", return_value=mock.Mock(
    returncode=1, stdout=""))
def test_system_python_none(mock_run):
    assert _system_python(Path("C:/proj")) is None


def test_venv_detection(tmp_path: Path):
    p = tmp_path / ".venv" / "Scripts" / "python.exe"
    p.parent.mkdir(parents=True)
    p.write_text("x", encoding="utf-8")
    assert _has_venv_python(tmp_path) == p
    assert _has_venv_python(Path("N:/nonexistent")) is None


def test_winpython_detection(tmp_path: Path):
    wp = tmp_path / "WPy64-312101" / "python" / "python.exe"
    wp.parent.mkdir(parents=True)
    wp.write_text("x", encoding="utf-8")
    assert _winpython_python(tmp_path) == wp


def test_chosen_python_defaults_first(tmp_path: Path):
    envs = [
        PyEnv(".venv", "v", "C:/a/python.exe", ""),
        PyEnv("system", "s", "C:/b/python.exe", ""),
    ]
    st = SetupState(tmp_path / ".setup_state.json")
    assert chosen_python(envs, st).id == ".venv"


def test_chosen_python_respects_state(tmp_path: Path):
    envs = [
        PyEnv(".venv", "v", "C:/a/python.exe", ""),
        PyEnv("system", "s", "C:/b/python.exe", ""),
    ]
    st = SetupState(tmp_path / ".setup_state.json")
    st.set("python_env_id", "system")
    assert chosen_python(envs, st).id == "system"


def test_chosen_python_falls_back_when_invalid(tmp_path: Path):
    envs = [PyEnv(".venv", "v", "C:/a/python.exe", "")]
    st = SetupState(tmp_path / ".setup_state.json")
    st.set("python_env_id", "ghost")
    assert chosen_python(envs, st).id == ".venv"