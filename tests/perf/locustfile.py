#!/usr/bin/env python3
"""Locust 性能/压力测试脚本。

场景：20 用户并发，持续 5 分钟，覆盖主要只读 API。
阈值：P95 < 500ms，错误率 < 1%。

使用方法：
    # 安装 locust
    pip install locust

    # 启动 Web UI（默认 http://localhost:8089）
    locust -f tests/perf/load_test.py

    # 无头模式运行
    locust -f tests/perf/load_test.py --headless \
        -u 20 -r 2 -t 5m \
        --host http://127.0.0.1:7870 \
        --only-summary

    # 运行并检查阈值（退出码 0 = 通过，1 = 失败）
    locust -f tests/perf/load_test.py --headless \
        -u 20 -r 2 -t 5m \
        --host http://127.0.0.1:7870 \
        --expect-workers 1 \
        --only-summary

所属项目：SeedVR2
"""

import json
import os
import sys
import time
from datetime import datetime

from locust import HttpUser, between, events, task


class SeedVR2User(HttpUser):
    """模拟一个 SeedVR2 WebUI 用户。"""

    # 请求间隔：1-3 秒随机
    wait_time = between(1, 3)

    @task(3)
    def view_health(self):
        """系统健康检查 — 最高频只读接口。"""
        with self.client.get(
            "/api/system/health",
            name="GET /api/system/health",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") != "ok":
                    response.failure(f"Health status not ok: {data}")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def view_history(self):
        """历史记录查询。"""
        with self.client.get(
            "/api/system/history?page=0&page_size=20",
            name="GET /api/system/history",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data.get("records"), list):
                    response.failure("History records is not a list")
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def view_settings(self):
        """设置读取。"""
        with self.client.get(
            "/api/system/settings",
            name="GET /api/system/settings",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def view_gpu_info(self):
        """GPU 信息查询。"""
        with self.client.get(
            "/api/system/gpu",
            name="GET /api/system/gpu",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def view_metrics(self):
        """性能指标查询。"""
        with self.client.get(
            "/api/system/metrics",
            name="GET /api/system/metrics",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def view_locales(self):
        """语言列表查询。"""
        with self.client.get(
            "/api/system/locales",
            name="GET /api/system/locales",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")


# ============================================================
# 阈值检查：P95 < 500ms，错误率 < 1%
# ============================================================

P95_THRESHOLD_MS = 500
ERROR_RATE_THRESHOLD = 0.01


@events.quitting.add_listener
def check_thresholds(environment, **kwargs):
    """在 Locust 退出时检查性能阈值。"""
    stats = environment.stats.total
    p95_response_time = None

    # 获取 P95 响应时间
    if environment.stats.entries:
        all_response_times = []
        for entry in environment.stats.entries.values():
            all_response_times.extend(entry.response_times)
        if all_response_times:
            sorted_times = sorted(all_response_times)
            idx = int(len(sorted_times) * 0.95)
            if idx >= len(sorted_times):
                idx = len(sorted_times) - 1
            p95_response_time = sorted_times[idx]

    error_rate = stats.fail_ratio if stats.num_requests > 0 else 0

    print("\n" + "=" * 60)
    print("性能测试结果摘要")
    print("=" * 60)
    print(f"总请求数:    {stats.num_requests}")
    print(f"失败请求数:  {stats.num_failures}")
    print(f"错误率:      {error_rate:.4%} (阈值 < {ERROR_RATE_THRESHOLD:.0%})")
    if p95_response_time is not None:
        print(f"P95 响应时间: {p95_response_time}ms (阈值 < {P95_THRESHOLD_MS}ms)")
    else:
        print("P95 响应时间: N/A (无请求)")
    print("=" * 60 + "\n")

    failures = []

    if p95_response_time is not None and p95_response_time > P95_THRESHOLD_MS:
        failures.append(
            f"P95 响应时间 {p95_response_time}ms 超过阈值 {P95_THRESHOLD_MS}ms"
        )

    if error_rate > ERROR_RATE_THRESHOLD:
        failures.append(
            f"错误率 {error_rate:.4%} 超过阈值 {ERROR_RATE_THRESHOLD:.0%}"
        )

    if failures:
        print("❌ 性能测试未通过:")
        for f in failures:
            print(f"  - {f}")
        environment.process_exit_code = 1
    else:
        print("✅ 性能测试通过！")
        environment.process_exit_code = 0


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """测试开始时打印信息。"""
    print(f"\n{'=' * 60}")
    print(f"SeedVR2 性能测试启动 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标地址: {environment.host}")
    print(f"{'=' * 60}\n")
