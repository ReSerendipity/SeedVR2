"""SeedVR2 - 通用工具模块包。

提供跨模块复用的无状态工具函数，按职责分类：

- response: 统一 API 响应包装，标准化 {success, data, error} 结构
- fts: SQLite FTS5 全文搜索查询转义，防止注入与语法错误
- retry: 异步指数退避重试工具，带随机抖动避免雪崩
"""
