"""国际化（i18n）支持模块 — JSON 三层回退 + 扁平优先查找

提供多语言文本翻译功能，支持中文、繁体中文、英文、日文、法文五种语言。
翻译文件以 JSON 格式存储在 locales/ 目录下。

核心特性：
    1. 三层 fallback 链保障翻译永不显示空值：
       指定语言 → 英文（en）回退 → key 本身兜底
    2. 翻译键查找支持两种模式：
       - 扁平键直接命中（整串 key 作为字典键，支持含 "." 的 key）
       - 命名空间嵌套（namespace.sub.key 逐段下钻）
       扁平优先于嵌套，避免含点号的 key 被误解析。
    3. 模块级缓存：翻译字典加载后缓存，避免重复 I/O。
    4. 保持 I18n 类 API 兼容：现有代码的 I18n() 实例、t() 方法等用法不变。

借鉴来源：TTS_MultiModel/bin/integrated_app/i18n.py
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOCALE_NAMES = {
    "zh": "中文",
    "zh-TW": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "fr": "Français",
}
"""语言代码到显示名称的映射。"""

LOCALE_ICONS = {
    "zh": "bi-flag",
    "zh-TW": "bi-flag",
    "en": "bi-flag",
    "ja": "bi-flag",
    "fr": "bi-flag",
}
"""语言代码到 Bootstrap Icons 图标类名的映射。"""

# 语言代码到 JSON 文件名的映射
_LANG_FILE_MAP: dict[str, str] = {
    "zh": "zh.json",
    "zh-CN": "zh.json",
    "zh-Hans": "zh.json",
    "zh-TW": "zh-TW.json",
    "zh-Hant": "zh-TW.json",
    "en": "en.json",
    "ja": "ja.json",
    "fr": "fr.json",
}

# 模块级翻译缓存字典（避免重复加载 JSON 文件）
_I18N_TRANSLATIONS: dict[str, dict[str, Any]] = {}

# 默认语言
_DEFAULT_LANG: str = "zh"


def _get_locales_dir() -> str:
    """获取 locales 目录路径"""
    return str(Path(__file__).parent / "locales")


def _load_translations(lang: str) -> dict[str, Any] | None:
    """加载指定语言的翻译字典（带缓存）。

    使用模块级 _I18N_TRANSLATIONS 字典作为缓存；缓存命中直接返回，
    否则从 JSON 文件读取并存入缓存。

    Args:
        lang: 语言代码（如 "zh"、"en"、"ja"、"fr"、"zh-TW"）。

    Returns:
        翻译字典；语言不支持、文件不存在或 JSON 解析失败时返回 None。
    """
    if lang in _I18N_TRANSLATIONS:
        return _I18N_TRANSLATIONS[lang]

    filename = _LANG_FILE_MAP.get(lang)
    if filename is None:
        # 尝试直接用 lang 作为文件名（如 "zh-TW.json"）
        filename = f"{lang}.json"

    filepath = os.path.join(_get_locales_dir(), filename)
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"国际化文件 JSON 解码失败: {filepath}")
        return None
    except PermissionError:
        logger.error(f"无法读取国际化文件（权限不足）: {filepath}")
        return None
    except OSError as e:
        logger.warning(f"读取国际化文件失败: {filepath}: {e}")
        return None

    _I18N_TRANSLATIONS[lang] = data
    logger.debug(f"加载翻译: {lang} ({len(data) if data else 0} 个顶层键)")
    return data


def _resolve_key(translations: dict[str, Any], key: str) -> str | None:
    """在翻译字典中解析翻译键（扁平优先 + 嵌套下钻）。

    先尝试扁平查找：以完整 key 作为字典键直接命中；
    失败后再使用 "." 分割并逐段下钻嵌套 dict。
    只有最终叶子节点是 str 类型才返回，dict 子树不返回。

    扁平优先的原因：扁平键允许形如 "version_1.0.label" 这种
    本身含点的字符串做 key，若先走嵌套模式会下钻失败。

    Args:
        translations: 翻译字典。
        key: 翻译键。

    Returns:
        翻译文本字符串；未找到或类型不匹配时返回 None。
    """
    # 1. 扁平查找：整串 key 直接命中
    try:
        if key in translations:
            result = translations[key]
            return result if isinstance(result, str) else None
    except (TypeError, AttributeError):
        pass

    # 2. 嵌套查找：点号分割逐段下钻
    if "." in key:
        try:
            parts = key.split(".")
            if not parts:
                return None
            nested: Any = translations
            for part in parts:
                if isinstance(nested, dict) and part in nested:
                    nested = nested[part]
                else:
                    return None
            return nested if isinstance(nested, str) else None
        except Exception:
            return None

    return None


def t(key: str, locale: str | None = None, default: str | None = None, **kwargs) -> str:
    """翻译函数，三层 fallback 链保障不显示空值。

    fallback 顺序：
    1. 指定语言的翻译字典 → _resolve_key
    2. 英文（en）翻译字典 → _resolve_key
    3. default 参数（若不为 None）或 key 本身作为最终兜底

    Args:
        key: 翻译键（支持点号分隔的嵌套键，如 "nav.video_restore"）。
        locale: 目标语言代码，None 时使用默认语言。
        default: 可选的自定义兜底文本；若为 None 则兜底为 key 本身。
        **kwargs: 格式化参数（使用 str.format() 替换）。

    Returns:
        str: 翻译结果或兜底字符串，永不返回 None。
    """
    lang = locale or _DEFAULT_LANG

    try:
        # 第一层：指定语言
        lang_dict = _load_translations(lang)
        if lang_dict is not None:
            result = _resolve_key(lang_dict, key)
            if result is not None:
                return _format(result, kwargs)

        # 第二层：英文回退
        if lang != "en":
            en_dict = _load_translations("en")
            if en_dict is not None:
                result = _resolve_key(en_dict, key)
                if result is not None:
                    return _format(result, kwargs)
    except Exception:
        pass

    # 第三层：兜底
    return default if default is not None else key


def _format(value: str, kwargs: dict) -> str:
    """对翻译值进行 str.format() 参数替换。

    Args:
        value: 翻译文本字符串。
        kwargs: 格式化参数。

    Returns:
        格式化后的字符串；格式化失败时返回原始值。
    """
    if not kwargs:
        return value
    try:
        return value.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return value


class I18n:
    """国际化翻译管理器（Facade 模式，委托给模块级函数）。

    保留此类以兼容现有代码的 I18n() 实例用法。
    内部实现委托给模块级 _load_translations / _resolve_key / t 函数。

    Attributes:
        locales_dir: 翻译文件目录路径（仅用于兼容，实际使用模块级路径）。
        default_locale: 默认语言代码。
        current_locale: 当前使用的语言代码。
    """

    def __init__(self, locales_dir: str | None = None, default_locale: str = "zh"):
        """初始化国际化管理器。

        Args:
            locales_dir: 翻译文件目录路径（兼容参数，实际使用模块级路径）。
            default_locale: 默认语言代码，默认 "zh"（中文）。
        """
        self.locales_dir = locales_dir or _get_locales_dir()
        global _DEFAULT_LANG
        _DEFAULT_LANG = default_locale
        self.default_locale = default_locale
        self.current_locale = default_locale

    def set_locale(self, locale: str):
        """设置当前语言

        Args:
            locale: 语言代码，如 "zh"、"en"、"ja"、"fr"、"zh-TW"。
        """
        # 验证语言是否可用
        if _load_translations(locale) is not None or locale in _LANG_FILE_MAP:
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

        Returns:
            翻译后的字符串
        """
        return t(key, locale=locale or self.current_locale, **kwargs)

    def get_available_locales(self) -> list:
        """获取可用语言代码列表。

        Returns:
            语言代码字符串列表，如 ["zh", "zh-TW", "en", "ja", "fr"]。
        """
        return list(_LANG_FILE_MAP.keys())

    def get_locale_name(self, locale: str) -> str:
        """获取语言的本地化显示名称。

        Args:
            locale: 语言代码。

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
        """可用语言代码列表（属性形式）。

        返回实际存在翻译文件的语言列表。
        """
        locales = []
        for lang in ["zh", "zh-TW", "en", "ja", "fr"]:
            if _load_translations(lang) is not None:
                locales.append(lang)
        return locales


# 全局实例
i18n = I18n()
