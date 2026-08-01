"""测试 common.logger 分布式感知日志工具。

覆盖:
- get_logger 幂等性：重复调用同名 logger 不重复添加 handler（防日志重复输出）
- get_logger 基础配置：level 为 INFO，附带默认 stdout handler
"""

from __future__ import annotations

import logging

from common.logger import _default_handler, get_logger


class TestGetLoggerIdempotent:
    """get_logger 幂等性 - 防止重复 addHandler 导致日志重复输出"""

    def test_repeated_calls_do_not_duplicate_handler(self):
        name = "test_logger_idempotent_case"
        # 清理可能的历史 handler，保证用例独立
        logging.getLogger(name).handlers.clear()

        first = get_logger(name)
        count_after_first = first.handlers.count(_default_handler)
        second = get_logger(name)
        count_after_second = second.handlers.count(_default_handler)

        assert first is second
        assert count_after_first == 1
        assert count_after_second == 1

    def test_many_calls_keep_single_handler(self):
        name = "test_logger_many_calls_case"
        logging.getLogger(name).handlers.clear()

        for _ in range(10):
            logger = get_logger(name)

        assert logger.handlers.count(_default_handler) == 1

    def test_level_is_info(self):
        logger = get_logger("test_logger_level_case")
        assert logger.level == logging.INFO
