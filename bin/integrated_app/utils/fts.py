"""FTS5 查询转义工具。

安全地处理用户输入用于 SQLite FTS5 全文搜索，防止查询语法错误和注入。

安全策略:
    - 转义所有 FTS5 特殊运算符和字符：AND/OR/NOT/NEAR、*、^、:、引号、括号
    - 将用户输入拆分为独立词元，每个词元用双引号包裹为 phrase 查询
    - 每个词元后附加 * 做前缀匹配，提升搜索体验
    - 多个词元用 OR 连接，保证任意词命中即返回结果
    - 空查询或纯特殊字符查询返回安全的 '""' 避免语法错误

FTS5 特殊字符说明:
    "   - phrase 引号
    *   - 前缀通配符
    ()  - 分组括号
    +-  - 优先级/排除
    :^  - 字段/权重
    空白 - 词元分隔符
"""
import re

_FTS5_SPECIAL_CHARS = re.compile(r'["\*\(\)\+\-:^\s]')


def escape_fts_query(query: str) -> str:
    """转义 FTS5 查询字符串，生成安全的 MATCH 表达式。

    处理流程：
    1. 空查询或 None 返回安全的 '""'
    2. 替换所有 FTS5 特殊字符为空格
    3. 按空白拆分词元
    4. 每个词元用双引号包裹并附加 * 做前缀匹配
    5. 多个词元用 OR 连接

    Args:
        query: 用户原始查询字符串，可能包含特殊字符

    Returns:
        str: 转义后的 FTS5 MATCH 表达式，可直接安全地用于 SQL 查询

    Example:
        >>> escape_fts_query('hello world')
        '"hello"* OR "world"*'
        >>> escape_fts_query('file: name?.txt')
        '"file"* OR "name"* OR "txt"*'
        >>> escape_fts_query('')
        '""'
    """
    if not query:
        return '""'
    cleaned = _FTS5_SPECIAL_CHARS.sub(" ", query).strip()
    if not cleaned:
        return '""'
    return " OR ".join(f'"{word}"*' for word in cleaned.split())
