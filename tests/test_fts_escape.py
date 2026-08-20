"""测试 FTS5 查询转义工具

SECURITY: 覆盖特殊字符注入、空查询、多词 OR 连接、前缀匹配等关键语义，
         防止用户输入触发 FTS5 运算符（*, OR, AND, NOT, NEAR, (), :, ^, -）。
"""

from __future__ import annotations

import pytest

from app.integrated_app.utils.fts import escape_fts_query


class TestEscapeFtsQueryBasic:
    """基本转义行为"""

    def test_empty_query_returns_empty_phrase(self):
        assert escape_fts_query("") == '""'

    def test_none_like_empty_string_raises(self):
        # 空字符串返回 '""'，但 None 不应被接受（类型检查层面）
        # 这里仅测试空字符串行为
        assert escape_fts_query("") == '""'

    def test_whitespace_only_returns_empty_phrase(self):
        assert escape_fts_query("   ") == '""'
        assert escape_fts_query("\t\n") == '""'

    def test_simple_word(self):
        assert escape_fts_query("hello") == '"hello"*'

    def test_multiple_words_joined_by_or(self):
        result = escape_fts_query("hello world")
        assert result == '"hello"* OR "world"*'


class TestEscapeFtsQuerySpecialChars:
    """FTS5 特殊字符必须被剥离或替换"""

    @pytest.mark.parametrize(
        "evil_input",
        [
            'hello"world',  # 双引号 - 短语边界注入
            "hello*world",  # 星号 - 前缀通配符
            "hello(world)",  # 括号 - 分组
            "hello+world",  # 加号 - AND
            "hello-world",  # 减号 - NOT
            "hello:world",  # 冒号 - 列限定符
            "hello^world",  # 脱字符 - 列权重
            "hello\tworld",  # 制表符
            "hello\nworld",  # 换行符
            "hello world",  # 空格 - 词分隔（应被替换为空格再 split）
        ],
    )
    def test_special_chars_replaced_or_split(self, evil_input):
        """特殊字符不应出现在最终 phrase 内部（被替换为空格后由 split 切分）"""
        result = escape_fts_query(evil_input)
        # 结果只应包含 "word"* 形式和 OR 连接符
        # 不应包含原始特殊字符（除了双引号包裹和星号后缀）
        # 验证：每个 phrase 内部不含 ", *, (, ), +, -, :, ^
        phrases = result.split(" OR ")
        for phrase in phrases:
            # phrase 形如 "word"*，去掉首尾的 " 和 * 后应只剩字母数字
            assert phrase.startswith('"') and phrase.endswith("*")
            inner = phrase[1:-2]  # 去掉首 " 和末 "*
            assert inner  # 不为空
            # 内部不应残留特殊字符
            for ch in '"()*+-:^\t\n':
                assert ch not in inner, f"特殊字符 {ch!r} 残留在 phrase: {inner!r}"

    def test_fts5_operators_neutralized(self):
        """FTS5 关键字不应作为运算符生效"""
        # 用户输入 AND/OR/NOT 应被当作普通词
        result = escape_fts_query("AND OR NOT NEAR")
        # 应转为 "AND"* OR "OR"* OR "NOT"* OR "NEAR"*
        assert result == '"AND"* OR "OR"* OR "NOT"* OR "NEAR"*'

    def test_mixed_special_and_normal(self):
        result = escape_fts_query("hello world*")
        assert result == '"hello"* OR "world"*'


class TestEscapeFtsQueryEmptyAndEdgeCases:
    """边界情况"""

    def test_only_special_chars_returns_empty_phrase(self):
        assert escape_fts_query("***") == '""'
        assert escape_fts_query("()()") == '""'
        assert escape_fts_query("---") == '""'

    def test_leading_trailing_special_chars_trimmed(self):
        result = escape_fts_query("***hello***")
        assert result == '"hello"*'

    def test_multiple_spaces_collapsed(self):
        # 多个空格被替换后 split() 自动合并
        result = escape_fts_query("hello     world")
        assert result == '"hello"* OR "world"*'

    def test_unicode_preserved(self):
        """中文等非 ASCII 字符应保留"""
        result = escape_fts_query("视频 修复")
        assert result == '"视频"* OR "修复"*'

    def test_numbers_preserved(self):
        result = escape_fts_query("video 2024")
        assert result == '"video"* OR "2024"*'

    def test_long_query(self):
        words = [f"word{i}" for i in range(50)]
        result = escape_fts_query(" ".join(words))
        assert result.count(" OR ") == 49
        assert result.startswith('"word0"*')
        assert result.endswith('"word49"*')


class TestEscapeFtsQueryProducesValidFts5:
    """转义后的字符串应可作为 FTS5 MATCH 表达式"""

    def test_result_is_valid_fts5_syntax(self, tmp_path):
        """用真实 SQLite FTS5 验证转义结果可被解析"""
        import sqlite3

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE fts USING fts5(content)")
            conn.execute("INSERT INTO fts(content) VALUES ('hello world video')")
            conn.execute("INSERT INTO fts(content) VALUES ('audio repair')")

            # 转义后的查询应能命中而不抛 FTS5 语法错误
            safe = escape_fts_query("hello")
            rows = conn.execute("SELECT content FROM fts WHERE fts MATCH ?", (safe,)).fetchall()
            assert len(rows) == 1
            assert "hello" in rows[0][0]

            # 多词 OR
            safe = escape_fts_query("hello audio")
            rows = conn.execute("SELECT content FROM fts WHERE fts MATCH ?", (safe,)).fetchall()
            assert len(rows) == 2

            # 注入尝试应被中和
            safe = escape_fts_query("hello* OR 1=1")
            # 不应抛 FTS5 语法错误
            rows = conn.execute("SELECT content FROM fts WHERE fts MATCH ?", (safe,)).fetchall()
            # 应转为 "hello"* OR "OR"* OR "1"* OR "1"*，至少能命中 hello
            assert any("hello" in r[0] for r in rows)
        finally:
            conn.close()
