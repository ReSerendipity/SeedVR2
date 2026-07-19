#!/usr/bin/env python3
"""SeedVR2 工具箱 - 模型状态注册中心（单例，线程安全）

使用 RLock 保护所有属性访问和状态变更，确保线程安全。
提供批量原子操作方法，支持单次锁获取完成多属性更新。

REFACTOR 改进:
- 观察者模式解耦 SSE 通知：不再直接 import event_bus，消除循环依赖风险 (B5)
- 监听器异常不再静默吞掉，记录 warning 日志 (E9)
"""
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 监听器回调签名：(event_name: str, payload: dict) -> None
Listener = Callable[[str, dict], None]


class _ModelRegistry:
    """模型状态注册中心 - 管理全局引擎实例和模型状态

    线程安全设计:
    - 使用 RLock（可重入锁）保护所有属性读写
    - 属性 setter 和状态变更方法均在锁保护下执行
    - 批量原子方法在单次锁获取内完成多属性更新

    观察者模式:
    - 外部模块（如 SSE event_bus）通过 add_listener 注册回调
    - 状态变更时通知所有监听器，不直接依赖任何下游模块 (B5)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._rlock = threading.RLock()
        self._model_loaded: bool = False
        self._current_model_size: str | None = None
        self._current_precision: str | None = None
        self._model_info: dict = {}
        self._engine: Any = None
        # REFACTOR: 观察者列表，替代直接 import event_bus (B5)
        self._listeners: list[Listener] = []
        self._initialized = True

    # ------------------------------------------------------------------
    # 属性访问（线程安全）
    # ------------------------------------------------------------------

    @property
    def model_loaded(self) -> bool:
        with self._rlock:
            return self._model_loaded

    @model_loaded.setter
    def model_loaded(self, value: bool) -> None:
        with self._rlock:
            self._model_loaded = value

    @property
    def current_model_size(self) -> str | None:
        with self._rlock:
            return self._current_model_size

    @current_model_size.setter
    def current_model_size(self, value: str | None) -> None:
        with self._rlock:
            self._current_model_size = value

    @property
    def current_precision(self) -> str | None:
        with self._rlock:
            return self._current_precision

    @current_precision.setter
    def current_precision(self, value: str | None) -> None:
        with self._rlock:
            self._current_precision = value

    @property
    def model_info(self) -> dict:
        with self._rlock:
            return dict(self._model_info)

    @model_info.setter
    def model_info(self, value: dict) -> None:
        with self._rlock:
            self._model_info = value if value is not None else {}

    # ------------------------------------------------------------------
    # 核心操作（线程安全）
    # ------------------------------------------------------------------

    def set_engine(self, engine) -> None:
        """设置引擎实例并同步状态"""
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
        """获取引擎实例"""
        with self._rlock:
            return self._engine

    def clear_engine(self) -> None:
        """清除引擎实例并重置状态"""
        with self._rlock:
            self._engine = None
            self._model_loaded = False
            self._current_model_size = None
            self._current_precision = None
            self._model_info = {}
        self._notify_listeners()

    def update_status(self, loaded: bool, model_size: str | None = None,
                      precision: str | None = None, info: dict | None = None) -> None:
        """手动更新模型状态"""
        with self._rlock:
            self._model_loaded = loaded
            self._current_model_size = model_size
            self._current_precision = precision
            if info is not None:
                self._model_info = info
        self._notify_listeners()

    def get_status(self) -> dict:
        """获取完整模型状态"""
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
        避免多次加锁导致中间状态可见。

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

        调用后下一次 _ModelRegistry() 将重新初始化所有状态。
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._initialized = False
                cls._instance = None

    # ------------------------------------------------------------------
    # 观察者模式：状态变更监听 (B5)
    # ------------------------------------------------------------------
    # REFACTOR: 原实现直接 import event_bus 造成 model_registry → routes.system.sse
    # 的耦合，存在循环依赖风险。改为观察者模式：registry 不依赖任何下游模块，
    # 由下游模块（app_server 启动时）主动注册监听器。

    def add_listener(self, listener: Listener) -> None:
        """注册状态变更监听器。

        监听器签名为 (event_name: str, payload: dict) -> None。
        典型用法：app_server 启动时注册 SSE event_bus.publish 作为监听器。
        """
        with self._rlock:
            if listener not in self._listeners:
                self._listeners.append(listener)
                logger.debug(f"已注册模型状态监听器: {listener}")

    def remove_listener(self, listener: Listener) -> None:
        """移除已注册的监听器"""
        with self._rlock:
            if listener in self._listeners:
                self._listeners.remove(listener)
                logger.debug(f"已移除模型状态监听器: {listener}")

    def _notify_listeners(self) -> None:
        """通知所有注册的监听器状态已变化。

        ROBUSTNESS: 单个监听器异常不影响其他监听器，且不静默吞掉 (E9)。
        快照 listeners 和 status 后在锁外调用，避免回调中再次加锁导致死锁。
        """
        with self._rlock:
            listeners = list(self._listeners)
        status = self.get_status()
        for listener in listeners:
            try:
                listener("model_status", status)
            except Exception as e:
                # E9: 记录监听器异常，不静默吞掉，也不影响其他监听器
                logger.warning(
                    f"模型状态监听器异常: {type(e).__name__}: {e}", exc_info=True
                )


# 全局单例
model_registry = _ModelRegistry()
