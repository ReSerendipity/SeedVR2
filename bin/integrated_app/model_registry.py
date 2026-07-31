#!/usr/bin/env python3
"""SeedVR2 - 模型状态注册中心模块（线程安全单例）

本模块实现全局模型状态注册中心，统一管理当前加载的引擎实例和模型状态，
是连接模型管理器、推理引擎与 SSE 事件推送的核心枢纽。

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, threading (RLock), 观察者模式, 单例模式

模块职责:
- 维护全局唯一的模型状态（是否加载、模型大小、精度、模型信息）
- 持有当前激活的推理引擎实例引用
- 提供线程安全的状态读写操作，支持批量原子更新
- 通过观察者模式向监听器（如 SSE event_bus）推送状态变更事件
- 解耦模型层与通知层，避免循环依赖

线程安全设计:
- 使用可重入锁 (RLock) 保护所有属性读写，防止并发竞态条件
- 所有属性 setter 和状态变更方法均在锁保护下执行
- 批量原子方法在单次锁获取内完成多属性更新，避免中间状态可见
- 监听器通知在锁外执行，避免回调中再次加锁导致死锁

观察者模式:
- 外部模块（如 SSE event_bus）通过 add_listener 注册状态变更回调
- 状态变更时通知所有已注册监听器，不直接依赖任何下游模块
- 单个监听器异常不影响其他监听器执行，并记录 warning 日志
"""
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Listener = Callable[[str, dict], None]
"""监听器回调函数类型别名

签名: (event_name: str, payload: dict) -> None
- event_name: 事件名称，当前仅支持 "model_status"
- payload: 事件负载字典，包含完整模型状态信息
"""


class _ModelRegistry:
    """模型状态注册中心 - 线程安全的单例类

    管理全局引擎实例和模型状态，提供原子化状态更新和观察者通知机制。

    Thread Safety:
        - 所有公共方法均通过 RLock 保护，可安全地从多线程调用
        - 属性访问使用 @property + 锁保护，保证读写原子性
        - 批量操作方法（如 set_engine_loaded）在单次锁获取内完成多个属性更新

    Observer Pattern:
        - 状态变更时自动通知所有已注册的监听器
        - 监听器列表本身也受锁保护，支持运行时动态注册/注销
        - 监听器通知在锁外执行，回调执行期间不阻塞其他线程的读操作

    Attributes:
        model_loaded (bool): 模型是否已加载完成
        current_model_size (str | None): 当前模型大小标识（如 "3b", "7b"）
        current_precision (str | None): 当前模型精度（如 "fp16", "fp8"）
        model_info (dict): 当前模型的详细信息字典
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """创建或返回单例实例（线程安全）

        使用双重检查锁定模式确保单例唯一性，
        初始化标记 _initialized 防止重复初始化。

        Returns:
            _ModelRegistry: 全局唯一的注册中心实例
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """初始化注册中心（仅执行一次）

        初始化内部状态、可重入锁和监听器列表。
        重复调用时直接返回，保证单例语义。
        """
        if self._initialized:
            return
        self._rlock = threading.RLock()
        self._model_loaded: bool = False
        self._current_model_size: str | None = None
        self._current_precision: str | None = None
        self._model_info: dict = {}
        self._engine: Any = None
        self._listeners: list[Listener] = []
        self._initialized = True

    # ------------------------------------------------------------------
    # 属性访问（线程安全）
    # ------------------------------------------------------------------

    @property
    def model_loaded(self) -> bool:
        """获取模型是否已加载

        Returns:
            bool: 模型已加载可用于推理返回 True，否则返回 False
        """
        with self._rlock:
            return self._model_loaded

    @model_loaded.setter
    def model_loaded(self, value: bool) -> None:
        """设置模型加载状态

        设置后自动通知所有监听器状态已变更。

        Args:
            value: 新的加载状态
        """
        with self._rlock:
            self._model_loaded = value
        self._notify_listeners()

    @property
    def current_model_size(self) -> str | None:
        """获取当前模型大小标识

        Returns:
            str | None: 模型大小字符串（如 "3b", "7b"），未加载时为 None
        """
        with self._rlock:
            return self._current_model_size

    @current_model_size.setter
    def current_model_size(self, value: str | None) -> None:
        """设置当前模型大小标识

        Args:
            value: 模型大小字符串，None 表示清除
        """
        with self._rlock:
            self._current_model_size = value
        self._notify_listeners()

    @property
    def current_precision(self) -> str | None:
        """获取当前模型精度标识

        Returns:
            str | None: 精度字符串（如 "fp16", "fp8"），未加载时为 None
        """
        with self._rlock:
            return self._current_precision

    @current_precision.setter
    def current_precision(self, value: str | None) -> None:
        """设置当前模型精度标识

        Args:
            value: 精度字符串，None 表示清除
        """
        with self._rlock:
            self._current_precision = value
        self._notify_listeners()

    @property
    def model_info(self) -> dict:
        """获取当前模型详细信息的副本

        返回字典副本而非引用，防止外部意外修改内部状态。

        Returns:
            dict: 模型信息字典副本
        """
        with self._rlock:
            return dict(self._model_info)

    @model_info.setter
    def model_info(self, value: dict) -> None:
        """设置当前模型详细信息

        Args:
            value: 模型信息字典，None 会被转换为空字典
        """
        with self._rlock:
            self._model_info = value if value is not None else {}
        self._notify_listeners()

    # ------------------------------------------------------------------
    # 核心操作（线程安全）
    # ------------------------------------------------------------------

    def set_engine(self, engine) -> None:
        """设置引擎实例并同步所有相关状态

        从引擎实例读取当前状态（是否加载、模型大小、精度、模型信息），
        原子化更新所有内部状态字段，然后通知监听器。

        Args:
            engine: 推理引擎实例（RestoreEngine 子类），None 表示清除引擎

        Note:
            - 设置非 None 引擎时会自动调用 engine.is_loaded() 和 engine.get_model_info() 同步状态
            - 设置 None 时会重置所有状态为初始值（未加载）
            - 状态更新完成后统一通知监听器一次
        """
        with self._rlock:
            self._engine = engine
            if engine is not None:
                self._model_loaded = engine.is_loaded()
                info = engine.get_model_info()
                self._model_info = info
                self._current_model_size = info.get("model_size")
                self._current_precision = info.get("precision")
            else:
                self._model_loaded = False
                self._current_model_size = None
                self._current_precision = None
                self._model_info = {}
        self._notify_listeners()

    def get_engine(self):
        """获取当前引擎实例

        Returns:
            RestoreEngine | None: 当前激活的推理引擎实例，未设置时为 None

        Warning:
            返回的是引擎引用而非副本，调用方不应修改引擎内部状态
        """
        with self._rlock:
            return self._engine

    def clear_engine(self) -> None:
        """清除引擎实例并重置所有状态

        等效于 set_engine(None)，将引擎引用置为 None 并重置所有模型状态，
        然后通知监听器。通常在模型卸载完成后调用。
        """
        with self._rlock:
            self._engine = None
            self._model_loaded = False
            self._current_model_size = None
            self._current_precision = None
            self._model_info = {}
        self._notify_listeners()

    def update_status(self, loaded: bool, model_size: str | None = None,
                      precision: str | None = None, info: dict | None = None) -> None:
        """手动更新模型状态（原子操作）

        在单次锁获取内同时更新多个状态字段，避免多次通知和中间状态。

        Args:
            loaded: 模型是否已加载
            model_size: 模型大小标识，None 表示不修改
            precision: 精度标识，None 表示不修改
            info: 模型信息字典，None 表示不修改
        """
        with self._rlock:
            self._model_loaded = loaded
            self._current_model_size = model_size
            self._current_precision = precision
            if info is not None:
                self._model_info = info
        self._notify_listeners()

    def get_status(self) -> dict:
        """获取完整模型状态快照

        Returns:
            dict: 包含所有状态字段的字典:
                - model_loaded: bool - 模型是否已加载
                - current_model_size: str | None - 当前模型大小
                - current_precision: str | None - 当前精度
                - model_info: dict - 模型详细信息
        """
        with self._rlock:
            return {
                "model_loaded": self._model_loaded,
                "current_model_size": self._current_model_size,
                "current_precision": self._current_precision,
                "model_info": self._model_info,
            }

    # ------------------------------------------------------------------
    # 批量原子操作
    # ------------------------------------------------------------------

    def set_engine_loaded(self, loaded: bool, model_size: str | None = None,
                          precision: str | None = None, info: dict | None = None) -> None:
        """批量原子设置引擎加载状态

        在单次锁获取内同时设置 loaded + size + precision + info，
        避免多次加锁导致中间状态被其他线程观察到。

        Args:
            loaded: 模型是否已加载
            model_size: 模型大小标识
            precision: 精度标识
            info: 模型信息字典
        """
        with self._rlock:
            self._model_loaded = loaded
            self._current_model_size = model_size
            self._current_precision = precision
            self._model_info = info if info is not None else {}
        self._notify_listeners()

    # ------------------------------------------------------------------
    # 测试支持
    # ------------------------------------------------------------------

    @classmethod
    def _reset(cls) -> None:
        """重置单例状态（仅用于测试）

        调用后下一次实例化 _ModelRegistry() 将重新初始化所有状态。
        此方法仅供单元测试使用，生产代码不应调用。

        Warning:
            重置会导致已注册的监听器和引擎引用丢失，仅在测试隔离场景使用
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._initialized = False
                cls._instance = None

    # ------------------------------------------------------------------
    # 观察者模式：状态变更监听
    # ------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        """注册状态变更监听器

        监听器会在模型状态发生任何变更时被调用，
        典型用法是 app_server 启动时注册 SSE event_bus.publish 作为监听器。

        Args:
            listener: 监听器回调函数，签名为 (event_name: str, payload: dict) -> None

        Note:
            - 重复添加相同监听器会被去重，不会重复触发
            - 监听器回调在锁外执行，可安全执行耗时操作
            - 单个监听器异常不影响其他监听器执行
        """
        with self._rlock:
            if listener not in self._listeners:
                self._listeners.append(listener)
                logger.debug(f"已注册模型状态监听器: {listener}")

    def remove_listener(self, listener: Listener) -> None:
        """移除已注册的监听器

        Args:
            listener: 要移除的监听器回调函数

        Note:
            移除不存在的监听器不会报错，静默忽略
        """
        with self._rlock:
            if listener in self._listeners:
                self._listeners.remove(listener)
                logger.debug(f"已移除模型状态监听器: {listener}")

    def _notify_listeners(self) -> None:
        """通知所有注册的监听器状态已变化（内部方法）

        执行流程:
        1. 在锁内创建监听器列表快照，避免通知期间列表被修改
        2. 在锁外获取当前状态快照
        3. 逐个调用监听器，捕获并记录单个监听器的异常

        Robustness:
            - 单个监听器抛出异常不影响其他监听器执行
            - 异常被记录为 warning 级别日志，不静默吞掉
            - 在锁外调用监听器，避免回调中再次加锁导致死锁
        """
        with self._rlock:
            listeners = list(self._listeners)
        status = self.get_status()
        for listener in listeners:
            try:
                listener("model_status", status)
            except Exception as e:
                logger.warning(
                    f"模型状态监听器异常: {type(e).__name__}: {e}", exc_info=True
                )


model_registry = _ModelRegistry()
"""全局模型状态注册中心单例实例

应用中所有模块应通过此实例访问和修改模型状态，
不应直接实例化 _ModelRegistry 类。
"""
