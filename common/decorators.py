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

"""Function decorators for distributed training, logging, timing, and threading.

This module provides reusable decorators that add cross-cutting concerns to
functions:

- **Logging**: ``log_on_entry`` logs function entry; ``log_runtime`` logs execution time.
- **Distributed synchronization**: ``barrier_on_entry`` inserts a barrier;
  ``local_rank_zero_only`` / ``global_rank_zero_only`` restrict execution to rank 0.
- **Assertions**: ``assert_only_global_rank_zero`` / ``assert_only_local_rank_zero``
  enforce rank-based access restrictions.
- **Threading**: ``new_thread`` runs the decorated function in a separate thread.

All distributed-aware decorators gracefully degrade to no-ops in single-GPU mode.
"""

import functools
import threading
import time
from collections.abc import Callable

import torch
import torch.distributed as dist

from common.distributed import barrier_if_distributed, get_global_rank, get_local_rank
from common.logger import get_logger

logger = get_logger(__name__)


def log_on_entry(func: Callable) -> Callable:
    """Decorator that logs the function name when the function is entered.

    When stacking multiple decorators, this should be applied innermost
    (closest to the function definition) to correctly capture the original
    function name.

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function that logs entry before calling the original function.

    Example:
        >>> @log_on_entry
        ... def train_step():
        ...     pass
    """

    def log_on_entry_wrapper(*args, **kwargs):
        logger.info(f"Entering {func.__name__}")
        return func(*args, **kwargs)

    return log_on_entry_wrapper


def barrier_on_entry(func: Callable) -> Callable:
    """Decorator that inserts a distributed barrier before function execution.

    Ensures all distributed ranks reach this point before any rank proceeds
    to execute the function body. Has no effect when not in distributed mode.

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function that synchronizes all ranks before execution.
    """

    def barrier_on_entry_wrapper(*args, **kwargs):
        barrier_if_distributed()
        return func(*args, **kwargs)

    return barrier_on_entry_wrapper


def _conditional_execute_wrapper_factory(execute: bool, func: Callable) -> Callable:
    """Factory creating a wrapper that conditionally executes the function.

    If ``execute`` is False, the function returns None without calling ``func``.
    After the conditional execution (or skip), a distributed barrier is called
    to ensure all ranks synchronize regardless of whether they executed.

    Args:
        execute: Whether to actually call ``func``.
        func: The function to conditionally execute.

    Returns:
        Wrapped function that executes conditionally and synchronizes afterward.
    """

    def conditional_execute_wrapper(*args, **kwargs):
        result = func(*args, **kwargs) if execute else None
        barrier_if_distributed()
        return result

    return conditional_execute_wrapper


def _asserted_wrapper_factory(condition: bool, func: Callable, err_msg: str = "") -> Callable:
    """Factory creating a wrapper that asserts a condition before execution.

    Used to enforce that certain functions are only called under specific
    conditions (e.g., only on rank zero). Raises AssertionError if the
    condition is not met.

    Args:
        condition: Boolean condition that must be True for execution.
        func: The function to guard.
        err_msg: Error message for the AssertionError if condition is False.

    Returns:
        Wrapped function that asserts before calling the original.
    """

    def asserted_execute_wrapper(*args, **kwargs):
        assert condition, err_msg
        result = func(*args, **kwargs)
        return result

    return asserted_execute_wrapper


def local_rank_zero_only(func: Callable) -> Callable:
    """Decorator that restricts function execution to local rank 0.

    On multi-GPU nodes, each node has a local rank 0 process. Only that
    process executes the function; other local ranks return None immediately.
    All ranks (including those that skipped) synchronize at a barrier afterward.

    This is typically used for per-node operations like data loading,
    checkpoint saving per node, or logging per node.

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function that only executes on local rank 0.
    """
    return _conditional_execute_wrapper_factory(get_local_rank() == 0, func)


def global_rank_zero_only(func: Callable) -> Callable:
    """Decorator that restricts function execution to global rank 0.

    Only the process with global rank 0 (across all nodes) executes the function;
    all other ranks return None immediately. All ranks synchronize at a barrier
    afterward.

    This is typically used for operations that should happen exactly once
    across the entire distributed job, such as logging to a shared file,
    saving checkpoints, or printing summary statistics.

    Args:
        func: The function to wrap.

    Returns:
        Wrapped function that only executes on global rank 0.
    """
    return _conditional_execute_wrapper_factory(get_global_rank() == 0, func)


def assert_only_global_rank_zero(func: Callable) -> Callable:
    """Decorator that asserts the caller is global rank 0.

    Unlike ``global_rank_zero_only`` which silently skips on non-zero ranks,
    this decorator raises an AssertionError if called from any rank other
    than global rank 0. Use this for functions that must never be called
    from non-zero ranks (e.g., functions that access rank-0-only resources).

    Args:
        func: The function to guard.

    Returns:
        Wrapped function that asserts global rank 0 before execution.
    """
    return _asserted_wrapper_factory(
        get_global_rank() == 0, func, err_msg="Not accessible to processes with global_rank != 0"
    )


def assert_only_local_rank_zero(func: Callable) -> Callable:
    """Decorator that asserts the caller is local rank 0.

    Unlike ``local_rank_zero_only`` which silently skips on non-zero local ranks,
    this decorator raises an AssertionError if called from any local rank other
    than 0. Use this for per-node functions that must only be called by the
    first GPU on each node.

    Args:
        func: The function to guard.

    Returns:
        Wrapped function that asserts local rank 0 before execution.
    """
    return _asserted_wrapper_factory(
        get_local_rank() == 0, func, err_msg="Not accessible to processes with local_rank != 0"
    )


def new_thread(func: Callable) -> Callable:
    """Decorator that runs the function in a new daemon thread.

    The wrapped function returns immediately with the Thread object, which
    can be joined to wait for completion. The thread is started automatically.

    Args:
        func: The function to run in a new thread.

    Returns:
        Wrapped function that returns a started ``threading.Thread`` object.

    Example:
        >>> @new_thread
        ... def background_save(data):
        ...     save_to_disk(data)
        >>> thread = background_save(large_data)
        >>> # ... do other work ...
        >>> thread.join()  # wait for save to complete
    """

    def new_thread_wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return new_thread_wrapper


def log_runtime(func: Callable) -> Callable:
    """Decorator that logs the function's execution time in seconds.

    Inserts distributed barriers before and after timing to ensure accurate
    measurement of synchronized operations. The elapsed time (from start to
    end of the function on all ranks) is logged at INFO level.

    Args:
        func: The function to time.

    Returns:
        Wrapped function that logs runtime after execution.
    """

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        if dist.is_initialized():
            torch.distributed.barrier()
        start = time.perf_counter()
        result = func(*args, **kwargs)
        if dist.is_initialized():
            torch.distributed.barrier()
        logger.info(f"Completed {func.__name__} in {time.perf_counter() - start:.3f} seconds.")
        return result

    return wrapped
