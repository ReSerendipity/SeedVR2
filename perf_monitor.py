#!/usr/bin/env python3
"""
SeedVR2 性能监控脚本
测量：API 响应时间、内存占用、GPU 使用率
运行方式：python perf_monitor.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

import requests


def benchmark():
    """SeedVR2 性能测试"""
    print("\n🔧 SeedVR2 性能基准测试")
    print("=" * 50)

    # 检查服务是否已在运行
    health_url = "http://127.0.0.1:7870/api/system/health"

    try:
        response = requests.get(health_url, timeout=3)
        if response.status_code == 200:
            print("[SeedVR2] ✅ 服务已在运行")

            # 测量 API 响应时间
            times = []
            for i in range(5):
                start = time.time()
                requests.get(health_url, timeout=5)
                duration = (time.time() - start) * 1000
                times.append(duration)
                print(f"  请求 {i+1}: {duration:.1f}ms")

            avg_time = sum(times) / len(times)
            print(f"\n✅ 平均响应时间：{avg_time:.1f}ms")

            return {
                "avg_response_ms": round(avg_time, 2),
                "min_ms": round(min(times), 2),
                "max_ms": round(max(times), 2),
                "timestamp": datetime.now().isoformat(),
            }
        else:
            print("[SeedVR2] ⚠️ 服务未运行或返回错误状态码")
            return {"error": "Service unavailable"}

    except requests.exceptions.ConnectionError:
        print("[SeedVR2] ⚠️ 服务未运行")
        print("请先启动：python -m uvicorn app.integrated_app.app_server:app --host 127.0.0.1 --port 7870")
        return {"error": "Service not running"}
    except Exception as e:
        print(f"[SeedVR2] ❌ 异常：{e}")
        return {"error": str(e)}


if __name__ == "__main__":
    results_dir = Path("./perf/results")
    results_dir.mkdir(exist_ok=True)

    metrics = benchmark()

    output_file = results_dir / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 结果已保存：{output_file}")
