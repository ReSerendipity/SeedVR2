"""路径安全守卫 - 白名单机制防止路径遍历

SECURITY: 替代 unified.py 中基于黑名单（系统目录）的 _is_safe_scan_path，
         改为白名单（仅允许在配置的允许目录内访问），
         彻底消除扫描任意用户目录泄露文件清单的风险。
"""
from pathlib import Path

from fastapi import HTTPException


class PathGuard:
    """路径白名单守卫

    仅允许访问配置的 allowed_base_dirs 子树内的路径。
    所有路径解析后再做白名单校验，防止 ..、符号链接等绕过。
    """

    def __init__(self, allowed_base_dirs: list[str | Path]):
        """初始化白名单

        Args:
            allowed_base_dirs: 允许访问的根目录列表（相对或绝对路径均可）
        """
        self._allowed: list[Path] = []
        for d in allowed_base_dirs:
            try:
                self._allowed.append(Path(d).resolve())
            except (OSError, ValueError):
                # 非法路径直接跳过，不让构造失败
                continue

    @property
    def allowed_dirs(self) -> list[Path]:
        """已配置的允许目录（已 resolve）"""
        return list(self._allowed)

    def is_safe_path(self, path: str | Path) -> bool:
        """检查路径是否在白名单内

        Args:
            path: 待检查的路径

        Returns:
            True 表示路径安全（在白名单内），False 表示不安全
        """
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            return False
        return any(resolved == base or base in resolved.parents for base in self._allowed)

    def assert_safe(self, path: str | Path, message: str = "路径不在允许范围内") -> None:
        """断言路径安全，否则抛出 403

        Args:
            path: 待检查的路径
            message: 错误消息（不应回显用户输入）

        Raises:
            HTTPException: 403 当路径不在白名单内
        """
        if not self.is_safe_path(path):
            raise HTTPException(status_code=403, detail=message)

    def assert_safe_scan(self, path: str | Path) -> None:
        """断言扫描路径安全（用于文件夹扫描端点）"""
        self.assert_safe(path, "不允许扫描该路径")

    def assert_safe_download(self, path: str | Path) -> None:
        """断言下载路径安全（用于文件下载端点）"""
        self.assert_safe(path, "不允许下载该路径")


def build_default_path_guard(project_root: str | Path, extra_dirs: list[str] | None = None) -> PathGuard:
    """从项目根目录构建默认 PathGuard

    默认允许的目录：
    - {project_root}/outputs
    - {project_root}/data/uploads
    - extra_dirs 中配置的额外目录

    Args:
        project_root: 项目根目录
        extra_dirs: 额外允许的目录（相对项目根或绝对路径）

    Returns:
        PathGuard 实例
    """
    root = Path(project_root)
    allowed = [
        root / "outputs",
        root / "data" / "uploads",
    ]
    if extra_dirs:
        for d in extra_dirs:
            p = Path(d)
            if not p.is_absolute():
                p = root / p
            allowed.append(p)
    return PathGuard(allowed)
