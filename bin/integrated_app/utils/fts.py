"""FTS5 查询转义工具

SECURITY: 防止用户输入触发 FTS5 特殊运算符（AND/OR/NOT/NEAR、*、^、:、括号），
         导致语法错误或意外结果。转义后做前缀匹配。
"""
import re

# FTS5 特殊字符：双引号、星号、括号、加减号、冒号、脱字符、空白
_FTS5_SPECIAL_CHARS = re.compile(r'["\*\(\)\+\-:^\s]')


def escape_fts_query(query: str) -> str:
    """转义 FTS5 查询字符串

    将用户输入拆分为词，每个词用双引号包裹并附加 * 做前缀匹配，
    多个词用 OR 连接，保证任意词命中即返回。

    Args:
        query: 用户原始查询字符串

    Returns:
        转义后的 FTS5 MATCH 表达式；空查询返回 '""' 避免语法错误
    """
    if not query:
        return '""'
    cleaned = _FTS5_SPECIAL_CHARS.sub(" ", query).strip()
    if not cleaned:
        return '""'
    # 双引号内的字符串是 FTS5 的 phrase，* 表示前缀匹配
    return " OR ".join(f'"{word}"*' for word in cleaned.split())
