"""Klar - 业务服务层

提取路由层中的业务逻辑，使路由层只负责 HTTP 协议适配。
- task_state: 线程安全的任务状态管理（替代 common.py 全局 OrderedDict）
- task_events: 任务进度事件总线（替代 progress 端点的 DB 高频轮询）
"""
