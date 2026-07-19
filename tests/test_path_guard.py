"""测试 PathGuard 路径白名单守卫

SECURITY: 覆盖白名单边界、路径遍历（..、符号链接）、非法路径、
         build_default_path_guard 默认目录构造等关键安全语义。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from bin.integrated_app.security.path_guard import (
    PathGuard,
    build_default_path_guard,
)


class TestPathGuardInit:
    """白名单初始化"""

    def test_resolves_allowed_dirs(self, tmp_path):
        sub = tmp_path / "outputs"
        sub.mkdir()
        guard = PathGuard([sub])
        assert guard.allowed_dirs == [sub.resolve()]

    def test_relative_path_resolved_to_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rel = Path("outputs")
        guard = PathGuard([rel])
        assert guard.allowed_dirs == [(tmp_path / "outputs").resolve()]

    def test_invalid_path_skipped_silently(self, tmp_path):
        # 含空字节的路径在 resolve 时抛 ValueError，应被跳过而非崩溃
        guard = PathGuard([tmp_path, "path/with\x00null"])
        assert guard.allowed_dirs == [tmp_path.resolve()]

    def test_extra_dirs_in_default_builder(self, tmp_path):
        guard = build_default_path_guard(tmp_path, extra_dirs=["custom_dir", "/abs/path"])
        allowed = guard.allowed_dirs
        assert (tmp_path / "outputs").resolve() in allowed
        assert (tmp_path / "data" / "uploads").resolve() in allowed
        assert (tmp_path / "custom_dir").resolve() in allowed
        assert Path("/abs/path").resolve() in allowed

    def test_extra_dirs_none_in_default_builder(self, tmp_path):
        guard = build_default_path_guard(tmp_path, extra_dirs=None)
        assert len(guard.allowed_dirs) == 2


class TestIsSafePath:
    """is_safe_path 边界覆盖"""

    def test_path_inside_allowed_dir(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        target = allowed / "sub" / "file.txt"
        assert guard.is_safe_path(target) is True

    def test_path_equals_allowed_dir(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        assert guard.is_safe_path(allowed) is True

    def test_path_outside_allowed_dir(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        outside = tmp_path / "secret" / "file.txt"
        assert guard.is_safe_path(outside) is False

    def test_path_traversal_with_dotdot(self, tmp_path):
        """测试 .. 路径遍历攻击"""
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        # 构造 outputs/../../etc/passwd 形式
        evil = allowed / ".." / ".." / "etc" / "passwd"
        assert guard.is_safe_path(evil) is False

    def test_absolute_path_outside_root(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        # 绝对路径指向系统目录
        assert guard.is_safe_path("C:/Windows/System32/evil.exe") is False

    def test_invalid_path_returns_false(self, tmp_path):
        guard = PathGuard([tmp_path])
        assert guard.is_safe_path("path/with\x00null") is False

    def test_multiple_allowed_dirs(self, tmp_path):
        a = tmp_path / "outputs"
        b = tmp_path / "data" / "uploads"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        guard = PathGuard([a, b])
        assert guard.is_safe_path(a / "x.png") is True
        assert guard.is_safe_path(b / "y.mp4") is True
        assert guard.is_safe_path(tmp_path / "other") is False


class TestAssertSafe:
    """assert_safe / assert_safe_scan / assert_safe_download 抛异常语义"""

    def test_assert_safe_passes_for_safe_path(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        # 不抛异常即通过
        guard.assert_safe(allowed / "x.png")

    def test_assert_safe_raises_403_for_unsafe_path(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        with pytest.raises(HTTPException) as exc_info:
            guard.assert_safe(tmp_path / "secret")
        assert exc_info.value.status_code == 403
        # 错误消息不应回显用户输入
        assert "secret" not in exc_info.value.detail

    def test_assert_safe_custom_message(self, tmp_path):
        guard = PathGuard([tmp_path / "outputs"])
        with pytest.raises(HTTPException) as exc_info:
            guard.assert_safe("/etc/passwd", message="自定义消息")
        assert exc_info.value.detail == "自定义消息"

    def test_assert_safe_scan(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        guard.assert_safe_scan(allowed)
        with pytest.raises(HTTPException) as exc_info:
            guard.assert_safe_scan(tmp_path / "other")
        assert exc_info.value.status_code == 403

    def test_assert_safe_download(self, tmp_path):
        allowed = tmp_path / "outputs"
        allowed.mkdir()
        guard = PathGuard([allowed])
        guard.assert_safe_download(allowed / "result.png")
        with pytest.raises(HTTPException) as exc_info:
            guard.assert_safe_download(tmp_path / "other" / "file")
        assert exc_info.value.status_code == 403


class TestBuildDefaultPathGuard:
    """build_default_path_guard 默认目录构造"""

    def test_default_dirs_present(self, tmp_path):
        guard = build_default_path_guard(tmp_path)
        allowed = guard.allowed_dirs
        assert (tmp_path / "outputs").resolve() in allowed
        assert (tmp_path / "data" / "uploads").resolve() in allowed

    def test_extra_relative_dir_resolved_against_root(self, tmp_path):
        guard = build_default_path_guard(tmp_path, extra_dirs=["custom"])
        assert (tmp_path / "custom").resolve() in guard.allowed_dirs

    def test_extra_absolute_dir_kept_absolute(self, tmp_path):
        abs_dir = tmp_path / "external"
        abs_dir.mkdir()
        guard = build_default_path_guard(tmp_path, extra_dirs=[str(abs_dir)])
        assert abs_dir.resolve() in guard.allowed_dirs

    def test_empty_extra_dirs(self, tmp_path):
        guard = build_default_path_guard(tmp_path, extra_dirs=[])
        assert len(guard.allowed_dirs) == 2
