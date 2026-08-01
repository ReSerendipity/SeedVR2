"""路径安全守卫 - 白名单机制防止路径遍历攻击。

SECURITY CRITICAL: 这是应用文件系统访问安全的核心防线，任何绕过都可能导致
任意文件读取/枚举漏洞。所有涉及用户指定路径的文件操作（扫描、下载、读取）
必须经过 PathGuard 校验，无一例外。

安全策略详解:
    1. 白名单机制 (Default Deny)
        - 默认拒绝所有路径访问，仅显式配置的 allowed_base_dirs 内的路径被允许
        - 替代原 unified.py 中基于黑名单（禁止访问系统目录）的方案，黑名单无法枚举所有危险路径
        - 彻底消除扫描任意用户目录泄露文件清单的风险（原 CWE-22 路径遍历漏洞修复）

    2. 路径规范化防御
        - 使用 Path.resolve() 解析所有符号链接、相对路径（..、.）、冗余分隔符
        - 解析后再做白名单匹配，防御以下绕过手段：
          * 相对路径遍历：../../etc/passwd
          * 符号链接绕过：允许目录内的符号链接指向外部
          * 路径编码绕过：URL 编码、Unicode 编码（由 Web 框架在更上层处理）
          * 混合大小写绕过：Windows 平台大小写不敏感，但 resolve() 处理

    3. 包含判断逻辑
        - resolved == base: 直接访问允许目录根
        - base in resolved.parents: 目标路径是允许目录的后代
        - 两种情况任一满足即放行，覆盖所有合法访问场景

    4. 错误处理安全
        - 非法路径（OSError/ValueError 如包含 NUL 字符、路径过长）直接视为不安全
        - 不向客户端暴露路径解析失败的具体原因，统一返回通用错误消息
        - 初始化时非法路径静默跳过，不让单个坏配置导致整个守卫失效

威胁模型:
    ┌──────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────┐
    │ 用户输入  │ ──► │ 路径解析      │ ──► │ 白名单匹配      │ ──► │ 文件系统 │
    │ (可能恶意)│     │ resolve()    │     │ parents 检查    │     │ 访问     │
    └──────────┘     └──────────────┘     └─────────────────┘     └──────────┘
                           │                     │
                           ▼                     ▼
                     规范化绝对路径          拒绝不在白名单路径

典型攻击防御示例:
    - 输入: outputs/../../../Windows/System32 → resolve 后跳出白名单 → 拒绝
    - 输入: data/uploads/link_to_etc (symlink) → resolve 指向 /etc → 不在白名单 → 拒绝
    - 输入: /etc/passwd (绝对路径) → 不在白名单 → 拒绝
    - 输入: outputs/../../.. (Windows 反斜杠) → resolve 规范化 → 拒绝
"""

from collections.abc import Sequence
from pathlib import Path

from fastapi import HTTPException


class PathGuard:
    """路径白名单守卫 - 防止路径遍历和任意文件访问。

    所有文件系统访问前必须调用 assert_safe() 或检查 is_safe_path()，
    未经过校验的路径不得用于任何 I/O 操作。

    安全保证:
        - 线程安全：所有方法无副作用，仅读取初始化时设置的 _allowed 列表
        - 无 TOCTOU 竞态：校验通过后文件可能被替换为符号链接，
            敏感操作应考虑在打开文件后再次校验（如使用 os.open with O_NOFOLLOW）
        - Windows 兼容：正确处理 Windows 路径（反斜杠、盘符、UNC 路径）

    Attributes:
        _allowed: 已解析为绝对路径的允许根目录列表
    """

    def __init__(self, allowed_base_dirs: Sequence[str | Path]):
        """初始化路径白名单守卫。

        所有路径在初始化时调用 resolve() 转为规范化绝对路径，
        非法路径（不存在、无权限、格式错误）静默跳过，不抛出异常中断初始化。

        Args:
            allowed_base_dirs: 允许访问的根目录列表，可以是相对或绝对路径；
                相对路径会相对于当前工作目录解析（建议使用绝对路径避免歧义）
        """
        self._allowed: list[Path] = []
        for d in allowed_base_dirs:
            try:
                self._allowed.append(Path(d).resolve())
            except (OSError, ValueError):
                continue

    @property
    def allowed_dirs(self) -> list[Path]:
        """获取已配置的允许目录列表（已 resolve 为绝对路径）。

        返回拷贝，防止外部修改内部状态。

        Returns:
            list[Path]: 允许的根目录绝对路径列表
        """
        return list(self._allowed)

    def is_safe_path(self, path: str | Path) -> bool:
        """检查路径是否在白名单允许范围内。

        执行流程：
        1. 将输入路径调用 resolve() 规范化为绝对路径
        2. 解析失败（非法字符、路径过长等）返回 False
        3. 检查解析后的路径是否等于任一允许目录，或是其子目录

        Args:
            path: 待检查的路径，可以是字符串或 Path 对象

        Returns:
            bool: True 表示路径安全（在白名单内），False 表示不安全应拒绝访问
        """
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            return False
        return any(resolved == base or base in resolved.parents for base in self._allowed)

    def assert_safe(self, path: str | Path, message: str = "路径不在允许范围内") -> None:
        """断言路径安全，不安全则抛出 403 Forbidden。

        安全提示：
            - message 参数应使用通用消息，不要回显用户输入的路径，
                防止攻击者通过错误消息探测文件系统结构

        Args:
            path: 待检查的路径
            message: 错误消息，默认使用通用提示，不应包含用户输入

        Raises:
            HTTPException: 403 状态码，当路径不在白名单内时抛出
        """
        if not self.is_safe_path(path):
            raise HTTPException(status_code=403, detail=message)

    def assert_safe_scan(self, path: str | Path) -> None:
        """断言文件夹扫描路径安全，用于 /api/restore/scan-folder 端点。

        扫描操作会列出目录内容，风险较高，使用专门的错误消息。

        Args:
            path: 待扫描的目录路径

        Raises:
            HTTPException: 403 状态码，路径不允许扫描时抛出
        """
        self.assert_safe(path, "不允许扫描该路径")

    def assert_safe_download(self, path: str | Path) -> None:
        """断言文件下载路径安全，用于文件下载端点。

        Args:
            path: 待下载的文件路径

        Raises:
            HTTPException: 403 状态码，路径不允许下载时抛出
        """
        self.assert_safe(path, "不允许下载该路径")


def build_default_path_guard(project_root: str | Path, extra_dirs: list[str] | None = None) -> PathGuard:
    """从项目根目录构建默认 PathGuard 实例。

    默认允许的目录（最小权限原则）：
        - {project_root}/outputs: 模型输出目录，修复结果存放位置
        - {project_root}/data/uploads: 用户上传文件目录
        - extra_dirs: 用户配置的额外允许目录（相对路径解析为相对于 project_root）

    Args:
        project_root: 项目根目录绝对路径
        extra_dirs: 额外允许的目录列表，路径可以是：
            - 绝对路径：直接加入白名单
            - 相对路径：相对于 project_root 解析后加入白名单

    Returns:
        PathGuard: 配置好的路径守卫实例
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
