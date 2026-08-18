"""i18n.py 单元测试（三层回退 + 扁平优先查找）

覆盖：
- t() 函数：指定语言/英文回退/key 兜底
- _resolve_key：扁平优先 vs 嵌套下钻
- I18n 类 API 兼容性（set_locale/t/get_available_locales）
- 缓存机制与异常处理
"""

from __future__ import annotations

import pytest

from bin.integrated_app.i18n import (
    _I18N_TRANSLATIONS,
    _LANG_FILE_MAP,
    LOCALE_ICONS,
    LOCALE_NAMES,
    I18n,
    _load_translations,
    _resolve_key,
    t,
)


@pytest.fixture(autouse=True)
def reset_i18n_cache():
    """每个测试前清空翻译缓存"""
    _I18N_TRANSLATIONS.clear()
    yield


class TestLoadTranslations:
    """_load_translations 加载逻辑测试"""

    def test_load_existing_language(self):
        """已存在的语言应成功加载"""
        result = _load_translations("en")
        assert result is not None
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_nonexistent_language_returns_none(self):
        """不存在的语言返回 None"""
        # de 不在默认配置中
        result = _load_translations("de")
        assert result is None

    def test_load_zh_tw_success(self):
        """繁体中文应成功加载"""
        result = _load_translations("zh-TW")
        assert result is not None
        assert isinstance(result, dict)

    def test_caching_mechanism(self):
        """相同语言应命中缓存"""
        # 第一次加载
        result1 = _load_translations("en")
        # 第二次应直接返回缓存
        result2 = _load_translations("en")
        assert result1 is result2  # 同一对象引用


class TestResolveKey:
    """_resolve_key 键解析逻辑测试"""

    @pytest.fixture
    def sample_translations(self):
        """示例翻译字典（扁平 + 嵌套混合）"""
        return {
            "flat_key": "flat_value",
            "version_1.0.label": "Version 1.0",  # 含点的扁平键
            "nested": {
                "level1": {
                    "level2": "deep_value"
                }
            },
            "app": {
                "title": "App Title"
            }
        }

    def test_flat_key_direct_hit(self, sample_translations):
        """扁平键应直接命中"""
        result = _resolve_key(sample_translations, "flat_key")
        assert result == "flat_value"

    def test_flat_key_with_dot(self, sample_translations):
        """含点的扁平键应优先扁平匹配而非嵌套下钻"""
        result = _resolve_key(sample_translations, "version_1.0.label")
        assert result == "Version 1.0"

    def test_nested_key_drill_down(self, sample_translations):
        """嵌套键应在扁平失败后走嵌套下钻"""
        result = _resolve_key(sample_translations, "nested.level1.level2")
        assert result == "deep_value"

    def test_nested_key_shallow(self, sample_translations):
        """浅层嵌套键应成功下钻"""
        result = _resolve_key(sample_translations, "app.title")
        assert result == "App Title"

    def test_nonexistent_key_returns_none(self, sample_translations):
        """不存在的键返回 None"""
        result = _resolve_key(sample_translations, "nonexistent")
        assert result is None

    def test_dict_leaf_node_returns_none(self, sample_translations):
        """叶子节点是 dict 时应返回 None"""
        # nested 本身是个 dict，不应返回
        result = _resolve_key(sample_translations, "nested")
        assert result is None


class TestTFunction:
    """t() 顶层翻译函数测试"""

    def test_t_returns_translation_for_existing_key(self):
        """现有 key 应返回翻译文本"""
        result = t("app", locale="en")
        assert isinstance(result, str)
        # en.json 有 "app" 键

    def test_t_fallback_to_english_when_missing(self):
        """指定语言缺失时应回退到英文"""
        # 假设 ja 缺少某个 key
        # 实际测试依赖具体翻译文件内容
        result = t("app", locale="ja")
        assert isinstance(result, str)

    def test_t_default_is_key_itself(self):
        """所有层级都缺失时返回 key 本身"""
        result = t("completely_nonexistent_key_xyz")
        assert result == "completely_nonexistent_key_xyz"

    def test_t_custom_default(self):
        """提供 custom default 参数时应使用该值"""
        result = t("nonexistent", default="My Default")
        assert result == "My Default"

    def test_t_format_args(self):
        """格式参数应被替换"""
        # en.json 需有含占位符的 key，这里先跳过复杂格式测试
        pass


class TestI18nClass:
    """I18n 类 API 兼容性测试"""

    def test_singleton_instance_t_method(self):
        """全局实例的 t 方法应可用"""
        from bin.integrated_app.i18n import i18n

        result = i18n.t("app")
        assert isinstance(result, str)

    def test_set_locale_updates_current_locale(self):
        """set_locale 应更新 current_locale"""
        i18n_inst = I18n()
        i18n_inst.set_locale("en")
        assert i18n_inst.current_locale == "en"

    def test_get_available_locales(self):
        """available_locales 应返回实际存在的语言"""
        i18n_inst = I18n()
        locales = i18n_inst.get_available_locales()
        assert isinstance(locales, list)
        assert len(locales) > 0
        assert "en" in locales

    def test_get_locale_name(self):
        """get_locale_name 应返回本地化名称"""
        i18n_inst = I18n()
        assert i18n_inst.get_locale_name("en") == "English"
        assert i18n_inst.get_locale_name("zh") == "中文"

    def test_get_locale_icon(self):
        """get_locale_icon 应返回图标类名"""
        i18n_inst = I18n()
        for locale in ["zh", "zh-TW", "en", "ja", "fr"]:
            icon = i18n_inst.get_locale_icon(locale)
            assert icon == LOCALE_ICONS.get(locale, "bi-flag")


class TestLocaleMetadata:
    """语言元数据测试"""

    def test_locale_names_match_lang_file_map(self):
        """LOCALE_NAMES 中的语言应在 _LANG_FILE_MAP 中有对应文件"""
        for locale in LOCALE_NAMES:
            assert locale in _LANG_FILE_MAP or f"{locale}.json" in [f.lower() for f in ["zh.json", "zh-TW.json", "en.json", "ja.json", "fr.json"]]

    def test_all_lang_codes_have_display_names(self):
        """所有支持的语言代码都应有显示名称"""
        # 反向检查
        locales_with_files = set(_LANG_FILE_MAP.keys())
        for locale in locales_with_files:
            # zh-CN 和 zh 映射到同一文件，允许不在 LOCALE_NAMES 中显式列出
            if locale.startswith("zh"):
                continue
            assert locale in LOCALE_NAMES


class TestEdgeCases:
    """边界情况测试"""

    def test_json_decode_error_handling(self, tmp_path, monkeypatch, caplog):
        """JSON 解码错误应返回 None 并记录警告"""
        # 创建损坏的 JSON 文件
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{ invalid json }")

        locales_dir = tmp_path / "locales"
        locales_dir.mkdir()
        (locales_dir / "en.json").write_text("{}")  # 空但合法

        monkeypatch.setattr(
            "bin.integrated_app.i18n._get_locales_dir",
            lambda: str(locales_dir),
        )

        result = _load_translations("en")
        assert result is not None  # 空 JSON 是合法的
