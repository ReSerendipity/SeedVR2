"""国际化支持模块 - 多语言切换 (中文/英文/日文/法文)"""
import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 语言显示名称映射
LOCALE_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "fr": "Français",
}

# 语言图标映射 (Bootstrap Icons)
LOCALE_ICONS = {
    "zh": "bi-flag",
    "en": "bi-flag",
    "ja": "bi-flag",
    "fr": "bi-flag",
}


class I18n:
    """国际化管理器"""

    def __init__(self, locales_dir: str = None, default_locale: str = "zh"):
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

    def t(self, key: str, locale: str = None, **kwargs) -> str:
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
        value = translations
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
        """获取可用语言列表"""
        return list(self._translations.keys())

    def get_locale_name(self, locale: str) -> str:
        """获取语言显示名称"""
        return LOCALE_NAMES.get(locale, locale)

    def get_locale_icon(self, locale: str) -> str:
        """获取语言图标"""
        return LOCALE_ICONS.get(locale, "bi-flag")

    @property
    def available_locales(self) -> list:
        return list(self._translations.keys())


# 全局实例
i18n = I18n()
