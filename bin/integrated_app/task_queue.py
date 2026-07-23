"""Klar - 单 Worker 任务队列

桌面端通常为单 GPU，因此使用一个 worker 串行执行修复任务，避免并发导致 OOM。
提供取消注册表，通过 asyncio.Event / Task.cancel 通知运行中任务退出。

ROBUSTNESS 改进:
- 任务级超时（asyncio.wait_for），防止卡死 worker (E6)
- worker 异常自动重启，最多 3 次连续重启后放弃 (E4)
- 队列 maxsize 可配，防止无界堆积导致 OOM (E3)
- 异常粒度细化，不再裸 except Exception (E2)

REFACTOR [E4-1]: on_cancel 回调机制
- 原实现 task_queue 超时后调用 asyncio.wait_for 取消 asyncio.Task，
  但底层 asyncio.to_thread 包装的推理线程无法被 cancel，GPU 资源持续占用
- 新增 on_cancel 回调，submit 时由调用方注入（通常为 engine.request_cancel），
  在超时或主动取消时调用，让推理线程在阶段切换点主动退出，确保 GPU 资源及时释放
"""
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

TaskFactory = Callable[[], Awaitable[None]]
CancelCallback = Callable[[], None]

# REFACTOR: 默认值外置为模块常量，支持从 config.runtime.task 注入 (F1)
DEFAULT_QUEUE_MAXSIZE = 100
DEFAULT_TASK_TIMEOUT_SECONDS = 3600  # 1 小时
MAX_WORKER_RESTARTS = 3


class TaskQueue:
    """单 worker 异步任务队列"""

    def __init__(
        self,
        *,
        maxsize: int = DEFAULT_QUEUE_MAXSIZE,
        task_timeout_seconds: int = DEFAULT_TASK_TIMEOUT_SECONDS,
    ):
        """初始化任务队列。

        Args:
            maxsize: 队列最大容量，满时 submit 将阻塞；<=0 表示无界（不推荐）
            task_timeout_seconds: 单个任务执行超时秒数，超时自动取消 (E6)
        """
        # E3: 有界队列，防止无界堆积导致内存溢出
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max(0, maxsize))
        self._cancelled_ids: set[str] = set()
        self._current_task_id: str | None = None
        self._current_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = False
        # E6: 任务级超时
        self._task_timeout = max(1, task_timeout_seconds)
        # E4: worker 重启计数
        self._restart_count = 0
        # REFACTOR [E4-1]: 任务级取消回调注册表
        # key=task_id, value=on_cancel 回调（通常为 engine.request_cancel）
        # 在超时或主动取消时调用，让底层同步推理线程在阶段切换点主动退出
        self._cancel_callbacks: dict[str, CancelCallback] = {}
        # 当前运行中任务的取消回调（_worker 中设置，便于超时时调用）
        self._current_cancel_callback: CancelCallback | None = None

    async def start(self):
        """启动队列 worker"""
        if self._worker_task is not None:
            return
        self._running = True
        self._restart_count = 0
        self._worker_task = asyncio.create_task(self._worker_guarded())
        logger.info("任务队列 worker 已启动")

    async def stop(self):
        """停止队列 worker，等待当前任务完成（不强制取消）"""
        self._running = False
        if self._worker_task is not None:
            # 放入一个哨兵让 worker 从 queue.get 中退出
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
        logger.info("任务队列 worker 已停止")

    async def submit(
        self,
        task_id: str,
        coro_factory: TaskFactory,
        on_cancel: CancelCallback | None = None,
    ):
        """提交一个任务到队列

        coro_factory 需要返回可 await 的协程对象；在 worker 实际执行时才会被调用，
        避免在提交阶段就创建协程。

        Args:
            task_id: 任务唯一标识
            coro_factory: 协程工厂，调用时返回新协程
            on_cancel: 取消回调（通常为 engine.request_cancel）。
                在任务超时或被主动取消时调用，让底层同步推理线程在阶段切换点
                主动退出，确保 GPU 资源及时释放。
                若为 None，则仅依靠 asyncio.Task.cancel 取消协程
                （对 to_thread 包装的同步代码无效，GPU 资源将持续占用至完成）。

        Raises:
            asyncio.QueueFull: 当队列已满（maxsize 生效）时立即抛出（非 await 场景）。
        """
        await self._queue.put((task_id, coro_factory, on_cancel))
        self._cancelled_ids.discard(task_id)
        if on_cancel is not None:
            self._cancel_callbacks[task_id] = on_cancel
        logger.info(f"任务 {task_id} 已提交到队列（on_cancel={'已注入' if on_cancel else '无'}）")

    def request_cancel(self, task_id: str) -> bool:
        """请求取消指定任务

        - 若任务正在运行：先调用 on_cancel 回调（让底层推理线程主动退出），
          再取消 asyncio.Task（兜底）。
        - 若任务仍在队列中：标记为已取消，worker 取出时跳过。

        REFACTOR [E4-1]: 优先调用 on_cancel 回调
        - 原实现仅调用 asyncio.Task.cancel，对 to_thread 包装的同步推理无效
        - 改为先调用 on_cancel（设置 cancel event），让推理线程在下一个阶段检查点
          主动抛出 InferenceCancelledError 退出，确保 GPU 资源及时释放
        - asyncio.Task.cancel 作为兜底，确保协程层面也能退出
        """
        self._cancelled_ids.add(task_id)
        # 先调用 on_cancel 回调，让底层推理线程主动退出
        on_cancel = self._cancel_callbacks.get(task_id)
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception as e:
                logger.warning(f"任务 {task_id} 的 on_cancel 回调异常: {e}", exc_info=True)

        if self._current_task_id == task_id and self._current_task and not self._current_task.done():
            self._current_task.cancel()
            logger.info(f"任务 {task_id} 正在运行，已发送取消信号（on_cancel + Task.cancel）")
            return True
        logger.info(f"任务 {task_id} 已标记为取消（仍在队列或未启动）")
        return True

    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被请求取消"""
        return task_id in self._cancelled_ids

    # REFACTOR: worker 守护层，捕获 _worker 的意外退出并自动重启 (E4)
    async def _worker_guarded(self):
        """worker 守护循环：异常退出后自动重启，最多 MAX_WORKER_RESTARTS 次"""
        while self._running:
            try:
                await self._worker()
                # 正常退出（收到哨兵）
                break
            except asyncio.CancelledError:
                logger.info("任务队列 worker 被取消")
                raise
            except Exception as e:
                # ROBUSTNESS: worker 因未预期异常退出，尝试重启
                self._restart_count += 1
                if self._restart_count > MAX_WORKER_RESTARTS:
                    logger.critical(
                        f"任务队列 worker 连续重启 {MAX_WORKER_RESTARTS} 次后仍失败，停止重启: {e}"
                    )
                    break
                logger.error(
                    f"任务队列 worker 异常退出，第 {self._restart_count} 次重启: {type(e).__name__}: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(1.0)  # 重启前短暂等待，避免热循环

    async def _worker(self):
        """队列 worker：一次只处理一个任务"""
        while self._running:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break

            if item is None:
                # 哨兵，用于优雅退出
                self._queue.task_done()
                break

            task_id, coro_factory, on_cancel = item

            if task_id in self._cancelled_ids:
                self._cancelled_ids.discard(task_id)
                self._cancel_callbacks.pop(task_id, None)
                self._queue.task_done()
                logger.info(f"任务 {task_id} 在队列中被跳过（已取消）")
                continue

            self._current_task_id = task_id
            self._current_cancel_callback = on_cancel
            try:
                coro = coro_factory()
                self._current_task = asyncio.create_task(coro)
                # E6: 任务级超时控制，防止卡死 worker
                await asyncio.wait_for(self._current_task, timeout=self._task_timeout)
            except asyncio.CancelledError:
                logger.info(f"任务 {task_id} 已取消")
                # 取消时已通过 request_cancel 调用过 on_cancel，此处不重复调用
            except TimeoutError:
                # asyncio.wait_for 超时抛出 TimeoutError（Python 3.11+），内部 Task 已被取消
                # REFACTOR [E4-1]: 超时后调用 on_cancel，让底层推理线程主动退出
                logger.error(
                    f"任务 {task_id} 执行超时（{self._task_timeout}s），已强制取消 (E6)"
                )
                self._invoke_cancel_callback(task_id, on_cancel, reason="超时")
            except asyncio.TimeoutError:
                # 兼容 Python 3.10- 的别名
                logger.error(
                    f"任务 {task_id} 执行超时（{self._task_timeout}s），已强制取消 (E6)"
                )
                self._invoke_cancel_callback(task_id, on_cancel, reason="超时")
            except Exception as e:
                # E2: 兜底捕获未预期异常，记录后继续处理下一个任务
                logger.exception(f"任务 {task_id} 执行异常: {e}")
            finally:
                self._current_task = None
                self._current_task_id = None
                self._current_cancel_callback = None
                self._cancel_callbacks.pop(task_id, None)
                self._queue.task_done()

    def _invoke_cancel_callback(self, task_id: str, on_cancel: CancelCallback | None, *, reason: str) -> None:
        """安全调用取消回调（超时或异常时使用）

        REFACTOR [E4-1]: 超时后通过 on_cancel 通知底层推理线程退出
        - asyncio.wait_for 超时仅取消 asyncio.Task，无法中断 to_thread 中的同步代码
        - 调用 on_cancel（engine.request_cancel）设置 cancel event，
          让推理线程在下一个阶段检查点主动抛出 InferenceCancelledError
        """
        if on_cancel is None:
            logger.warning(
                f"任务 {task_id} {reason}，但未注入 on_cancel 回调，"
                f"底层推理线程可能继续运行，GPU 资源将持续占用至完成"
            )
            return
        try:
            on_cancel()
            logger.info(f"任务 {task_id} {reason}，已调用 on_cancel 回调通知底层退出")
        except Exception as e:
            logger.warning(f"任务 {task_id} {reason}，on_cancel 回调异常: {e}", exc_info=True)

    @property
    def current_task_id(self) -> str | None:
        """当前正在运行的任务 ID"""
        return self._current_task_id

    @property
    def queue_size(self) -> int:
        """当前队列中待处理的任务数"""
        return self._queue.qsize()
