"""国际化（i18n）支持模块

提供多语言文本翻译功能，支持中文、英文、日文、法文四种语言。
翻译文件以 YAML 格式存储在 locales/ 目录下，支持嵌套键（点号分隔访问）
和 Python str.format() 参数替换。

翻译回退策略: 指定语言找不到键时，自动回退到默认语言（中文），
默认语言也找不到时返回键名本身，保证 UI 不会出现空白。
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

LOCALE_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "fr": "Français",
}
"""语言代码到显示名称的映射。"""

LOCALE_ICONS = {
    "zh": "bi-flag",
    "en": "bi-flag",
    "ja": "bi-flag",
    "fr": "bi-flag",
}
"""语言代码到 Bootstrap Icons 图标类名的映射。"""


class I18n:
    """国际化翻译管理器。

    负责加载 YAML 翻译文件、管理当前语言设置、提供键值翻译查询。
    支持嵌套键（如 "nav.video_restore"）和格式化参数替换。

    Attributes:
        locales_dir: 翻译文件目录路径。
        default_locale: 默认语言代码，当翻译缺失时回退到此语言。
        current_locale: 当前使用的语言代码。
        _translations: 翻译数据字典，{locale: {key: value}}。
    """

    def __init__(self, locales_dir: str | None = None, default_locale: str = "zh"):
        """初始化国际化管理器。

        Args:
            locales_dir: 翻译文件目录路径，None 时默认使用包内 locales/ 目录。
            default_locale: 默认语言代码，默认 "zh"（中文）。
        """
        if locales_dir is None:
            locales_dir = str(Path(__file__).parent / "locales")
        self.locales_dir = locales_dir
        self.default_locale = default_locale
        self.current_locale = default_locale
        self._translations: dict[str, dict[str, str]] = {}
        self._load_all_translations()

    def _load_all_translations(self):
        """加载所有翻译文件"""
        if not os.path.exists(self.locales_dir):
            logger.warning(f"翻译目录不存在: {self.locales_dir}")
            return

        for filename in os.listdir(self.locales_dir):
            if filename.endswith((".yaml", ".yml")):
                locale = os.path.splitext(filename)[0]
                filepath = os.path.join(self.locales_dir, filename)
                try:
                    with open(filepath, encoding="utf-8") as f:
                        self._translations[locale] = yaml.safe_load(f) or {}
                    logger.info(f"加载翻译: {locale}")
                except Exception as e:
                    logger.error(f"加载翻译文件失败 {filepath}: {e}")

    def set_locale(self, locale: str):
        """设置当前语言"""
        if locale in self._translations:
            self.current_locale = locale
        else:
            logger.warning(f"语言 {locale} 不可用，使用默认语言 {self.default_locale}")
            self.current_locale = self.default_locale

    def t(self, key: str, locale: str | None = None, **kwargs) -> str:
        """翻译文本

        Args:
            key: 翻译键（支持点号分隔的嵌套键，如 "nav.video_restore"）
            locale: 指定语言（可选，默认使用当前语言）
            **kwargs: 格式化参数
        """
        locale = locale or self.current_locale
        translations = self._translations.get(locale, {})

        # 支持嵌套键
        keys = key.split(".")
        value: Any = translations
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break

        if value is None:
            # 回退到默认语言
            if locale != self.default_locale:
                return self.t(key, self.default_locale, **kwargs)
            return key  # 最后回退到键本身

        # 格式化
        if kwargs and isinstance(value, str):
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError):
                return value

        return str(value)

    def get_available_locales(self) -> list:
        """获取已加载的可用语言代码列表。

        Returns:
            语言代码字符串列表，如 ["zh", "en", "ja", "fr"]。
        """
        return list(self._translations.keys())

    def get_locale_name(self, locale: str) -> str:
        """获取语言的本地化显示名称。

        Args:
            locale: 语言代码，如 "zh"、"en"。

        Returns:
            语言显示名称，未知语言代码返回代码本身。
        """
        return LOCALE_NAMES.get(locale, locale)

    def get_locale_icon(self, locale: str) -> str:
        """获取语言对应的 Bootstrap Icons 图标类名。

        Args:
            locale: 语言代码。

        Returns:
            Bootstrap Icons 类名，默认为 "bi-flag"。
        """
        return LOCALE_ICONS.get(locale, "bi-flag")

    @property
    def available_locales(self) -> list:
        """已加载的可用语言代码列表（属性形式）。

        Returns:
            语言代码字符串列表。
        """
        return list(self._translations.keys())


# 全局实例
i18n = I18n()
