# // Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# //
# // Licensed under the Apache License, Version 2.0 (the "License");
# // you may not use this file except in compliance with the License.
# // You may obtain a copy of the License at
# //
# //     http://www.apache.org/licenses/LICENSE-2.0
# //
# // Unless required by applicable law or agreed to in writing, software
# // distributed under the License is distributed on an "AS IS" BASIS,
# // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# // See the License for the specific language governing permissions and
# // limitations under the License.

"""Distributed-aware logging utility.

This module provides a centralized logging configuration that automatically
includes rank information in log messages when running in distributed mode.
The log format includes:
- Timestamp (asctime)
- Global rank (when world_size > 1)
- Local rank (when world_size > 1)
- Thread name (truncated to 12 characters)
- Logger name
- Log level (truncated to 5 characters)
- Log message

All log output is directed to stdout for consistent capture in distributed
training environments.
"""

import logging
import sys
from typing import Optional

from common.distributed import get_global_rank, get_local_rank, get_world_size

_default_handler = logging.StreamHandler(sys.stdout)
_default_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s "
        + (f"[Rank:{get_global_rank()}]" if get_world_size() > 1 else "")
        + (f"[LocalRank:{get_local_rank()}]" if get_world_size() > 1 else "")
        + "[%(threadName).12s][%(name)s][%(levelname).5s] "
        + "%(message)s"
    )
)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get or create a logger with distributed-aware formatting.

    The returned logger is configured with a stdout StreamHandler that includes
    rank information in the format when running distributed. The logger level
    is set to INFO.

    Note:
        This function adds the default handler each time it is called. Callers
        should typically call this once per module at import time and reuse the
        returned logger instance, e.g.::

            logger = get_logger(__name__)

    Args:
        name: Logger name, typically the module's ``__name__``. If None, returns
            the root logger. Defaults to None.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)
    logger.addHandler(_default_handler)
    logger.setLevel(logging.INFO)
    return logger
