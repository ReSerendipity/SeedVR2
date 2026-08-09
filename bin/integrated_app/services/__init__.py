"""SeedVR2 - 业务服务层包。

提取路由层中的业务逻辑，使路由层只负责 HTTP 协议解析与适配，遵循关注点分离原则。

核心服务模块:
    - task_state: 线程安全的任务状态双层存储服务（内存缓存 + SQLite 持久化），
        替代原 common.py 中无锁保护的全局 OrderedDict
    - task_events: 任务进度事件总线（发布/订阅模式），
        替代原 progress 端点的数据库高频轮询方案

设计模式:
    - 服务层模式 (Service Layer Pattern)：封装业务逻辑，路由层仅做 HTTP 适配
    - 单例模式：task_state_store 和 task_event_bus 为应用全局单例
    - 观察者模式：task_events 通过发布/订阅实现进度推送
    - 缓存 aside 模式：task_state 内存缓存加速读取，数据库为唯一可信源

架构约束:
    - 服务层不应直接依赖 FastAPI Request/Response 对象
    - 服务层方法要么是线程安全的同步方法，要么是正确的 async 协程
    - 状态修改必须通过服务层 API，禁止路由层直接操作全局状态
"""
