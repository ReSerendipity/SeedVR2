#!/usr/bin/env python3
"""SeedVR2 API 调用示例（Python）。

本脚本演示如何通过 Python requests 库调用 SeedVR2 的 REST API，
涵盖以下场景：
1. 单文件上传修复
2. 批量文件夹修复
3. SSE 实时进度监听
4. 历史记录查询
5. 结果文件下载
6. 系统健康检查与 GPU 信息查询
7. 模型加载/卸载/状态查询

使用前请确保：
1. SeedVR2 服务已启动（默认 http://127.0.0.1:7870）
2. 模型已加载（可通过 /api/system/model/load 加载）
3. 安装 requests 库：pip install requests

Usage:
    python api_example.py [--base-url http://127.0.0.1:7870]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("请先安装 requests 库：pip install requests")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="SeedVR2 API 调用示例")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:7870",
        help="SeedVR2 服务地址（默认 http://127.0.0.1:7870）",
    )
    return parser.parse_args()


def check_health(base_url: str) -> dict:
    """检查服务健康状态。

    GET /api/system/ping — 轻量级存活探针
    GET /api/system/health — 详细系统健康检查
    """
    print("\n=== 1. 健康检查 ===")

    # 轻量探针
    resp = requests.get(f"{base_url}/api/system/ping", timeout=10)
    resp.raise_for_status()
    ping = resp.json()
    print(f"  Ping: {ping}")

    # 详细健康检查
    resp = requests.get(f"{base_url}/api/system/health", timeout=10)
    resp.raise_for_status()
    health = resp.json()
    print(f"  Status: {health.get('status')}")
    print(f"  Uptime: {health.get('uptime_seconds', 0):.1f}s")
    sys_info = health.get("system", {})
    print(f"  Platform: {sys_info.get('platform', 'unknown')}")
    print(f"  Python: {sys_info.get('python_version', 'unknown')}")
    print(f"  CPU cores: {sys_info.get('cpu_count', 0)}")
    print(f"  Memory: {sys_info.get('memory_available_gb', 0):.1f} / {sys_info.get('memory_total_gb', 0):.1f} GB")
    gpu_info = health.get("gpu", {})
    print(f"  GPU: {gpu_info.get('device_name', 'N/A')} (available={gpu_info.get('is_gpu_available', False)})")

    return health


def get_gpu_info(base_url: str) -> dict:
    """获取 GPU 详细信息。

    GET /api/system/gpu — GPU 硬件信息（显存、利用率、CUDA 版本等）
    GET /api/system/gpu/vram-estimate — VRAM 需求估算
    GET /api/system/gpu/recommend-params — 推荐参数
    """
    print("\n=== 2. GPU 信息 ===")

    resp = requests.get(f"{base_url}/api/system/gpu", timeout=10)
    resp.raise_for_status()
    gpu = resp.json()
    print(f"  Device: {gpu.get('device_name', 'N/A')}")
    print(f"  VRAM: {gpu.get('vram_available_mb', 0)} / {gpu.get('vram_total_mb', 0)} MB")
    print(f"  Utilization: {gpu.get('utilization_pct', 0)}%")
    print(f"  CUDA: {gpu.get('cuda_version', 'N/A')}")

    # VRAM 估算示例
    print("\n  --- VRAM 估算 ---")
    resp = requests.get(
        f"{base_url}/api/system/gpu/vram-estimate",
        params={"model_name": "3b", "precision": "fp16", "width": 1920, "height": 1080, "num_frames": 1},
        timeout=10,
    )
    resp.raise_for_status()
    estimate = resp.json()
    if estimate.get("success"):
        data = estimate["data"]
        print(f"  Model: {data['model_name']} ({data['precision']})")
        print(f"  Input: {data['input_width']}x{data['input_height']}, {data['num_frames']} frames")
        print(f"  Estimated VRAM: {data['estimated_vram_gb']:.2f} GB")

    # 参数推荐
    print("\n  --- 参数推荐 ---")
    resp = requests.get(
        f"{base_url}/api/system/gpu/recommend-params",
        params={"model_name": "3b", "width": 1920, "height": 1080, "num_frames": 1},
        timeout=10,
    )
    resp.raise_for_status()
    recommend = resp.json()
    if recommend.get("success"):
        rec = recommend["data"]
        print(f"  Recommended precision: {rec.get('precision')}")
        print(f"  BlockSwap: {rec.get('enable_blockswap')} (blocks={rec.get('blocks_to_swap')})")
        print(f"  Risk: {rec.get('risk')}")

    return gpu


def load_model(base_url: str, size: str = "3b", precision: str = "fp16") -> dict:
    """加载模型到 GPU。

    POST /api/system/model/load — 加载模型
    GET /api/system/model/status — 查询模型状态
    """
    print(f"\n=== 3. 加载模型 ({size}/{precision}) ===")

    # 先检查当前状态
    resp = requests.get(f"{base_url}/api/system/model/status", timeout=10)
    resp.raise_for_status()
    status = resp.json()
    if status.get("loaded"):
        print(f"  模型已加载: {status.get('model_size', 'unknown')}")
        return status

    # 加载模型
    resp = requests.post(
        f"{base_url}/api/system/model/load",
        json={"size": size, "precision": precision},
        timeout=300,  # 模型加载可能需要较长时间
    )
    if resp.status_code == 200:
        result = resp.json()
        print(f"  加载成功: {result}")
        return result
    else:
        print(f"  加载失败: {resp.status_code} - {resp.text}")
        return {}


def upload_and_restore(base_url: str, file_path: str) -> str | None:
    """上传单文件并创建修复任务。

    POST /api/restore/ — 上传文件或指定文件夹创建修复任务

    Args:
        base_url: 服务地址
        file_path: 本地图片/视频文件路径

    Returns:
        任务 ID，失败返回 None
    """
    print(f"\n=== 4. 单文件修复: {file_path} ===")

    if not os.path.exists(file_path):
        print(f"  文件不存在: {file_path}")
        return None

    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        data = {
            "task_type": "auto",
            "dit_model": "3b_fp16",
            "seed": "42",
            "resolution": "2048",
        }
        resp = requests.post(f"{base_url}/api/restore/", files=files, data=data, timeout=60)

    if resp.status_code == 200:
        result = resp.json()
        if result.get("success"):
            task_info = result["data"]
            print("  任务已创建:")
            print(f"    Task ID: {task_info['task_id']}")
            print(f"    Record ID: {task_info['record_id']}")
            print(f"    Type: {task_info['task_type']}")
            print(f"    Status: {task_info['status']}")
            return task_info["task_id"]
        else:
            print(f"  创建失败: {result.get('error')}")
            return None
    else:
        print(f"  请求失败: {resp.status_code} - {resp.text}")
        return None


def batch_restore(base_url: str, folder_path: str) -> str | None:
    """批量修复文件夹中的媒体文件。

    POST /api/restore/batch — 创建批量修复任务
    GET /api/restore/batch/{batch_id}/progress — 查询批量进度
    """
    print(f"\n=== 5. 批量修复: {folder_path} ===")

    data = {
        "folder_path": folder_path,
        "task_type": "auto",
        "dit_model": "3b_fp16",
        "seed": "42",
    }
    resp = requests.post(f"{base_url}/api/restore/batch", data=data, timeout=60)

    if resp.status_code == 200:
        result = resp.json()
        if result.get("success"):
            batch_info = result["data"]
            print("  批量任务已创建:")
            print(f"    Batch ID: {batch_info['batch_id']}")
            print(f"    Total files: {batch_info['total']}")
            print(f"    Media type: {batch_info['media_type']}")
            return batch_info["batch_id"]
        else:
            print(f"  创建失败: {result.get('error')}")
            return None
    else:
        print(f"  请求失败: {resp.status_code} - {resp.text}")
        return None


def listen_sse_progress(base_url: str, task_id: str, timeout: int = 300):
    """通过 SSE 监听任务实时进度。

    GET /api/restore/{task_id}/progress — SSE 实时进度推送

    使用 requests 的流式响应处理 SSE 事件。

    Args:
        base_url: 服务地址
        task_id: 任务 ID
        timeout: 最大监听时间（秒）
    """
    print(f"\n=== 6. SSE 进度监听 (task={task_id}) ===")

    url = f"{base_url}/api/restore/{task_id}/progress"
    start_time = time.time()

    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if time.time() - start_time > timeout:
                    print("  超时，停止监听")
                    break

                if not line:
                    continue

                # SSE 数据行以 "data: " 开头
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    status = data.get("status", "unknown")
                    progress = data.get("progress", 0)
                    current_frame = data.get("current_frame", 0)
                    total_frames = data.get("total_frames", 0)
                    message = data.get("message", "")

                    if total_frames > 0:
                        print(f"  [{status}] {progress:.1f}% (frame {current_frame}/{total_frames}) {message}")
                    else:
                        print(f"  [{status}] {progress:.1f}% {message}")

                    # 终态处理
                    if status in ("completed", "failed", "cancelled", "timeout"):
                        print(f"  任务结束: {status}")
                        break

    except requests.exceptions.Timeout:
        print("  SSE 连接超时")
    except Exception as e:
        print(f"  SSE 监听异常: {e}")


def get_task_result(base_url: str, task_id: str) -> dict | None:
    """获取任务结果信息。

    GET /api/restore/{task_id}/result — 获取任务结果
    """
    print(f"\n=== 7. 获取结果 (task={task_id}) ===")

    resp = requests.get(f"{base_url}/api/restore/{task_id}/result", timeout=10)
    if resp.status_code == 200:
        result = resp.json()
        if result.get("success"):
            data = result["data"]
            print(f"  Status: {data.get('status')}")
            if data.get("output_path"):
                print(f"  Output: {data['output_path']}")
            if data.get("file_size"):
                print(f"  Size: {data['file_size']} bytes")
            if data.get("error"):
                print(f"  Error: {data['error']}")
            return data
    else:
        print(f"  请求失败: {resp.status_code}")
    return None


def download_result(base_url: str, task_id: str, output_dir: str = "downloads"):
    """下载修复结果文件。

    GET /api/restore/{task_id}/download — 下载修复结果
    """
    print(f"\n=== 8. 下载结果 (task={task_id}) ===")

    os.makedirs(output_dir, exist_ok=True)
    resp = requests.get(f"{base_url}/api/restore/{task_id}/download", stream=True, timeout=60)

    if resp.status_code == 200:
        # 从 Content-Disposition 获取文件名
        filename = task_id
        content_disp = resp.headers.get("content-disposition", "")
        if "filename=" in content_disp:
            filename = content_disp.split("filename=")[-1].strip('"').strip("'")

        # 如果没有扩展名，根据 Content-Type 推断
        if "." not in filename:
            content_type = resp.headers.get("content-type", "")
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "video/mp4": ".mp4"}
            filename += ext_map.get(content_type, ".bin")

        output_path = os.path.join(output_dir, filename)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  已下载: {output_path} ({os.path.getsize(output_path)} bytes)")
    else:
        print(f"  下载失败: {resp.status_code} - {resp.text}")


def query_history(base_url: str, page: int = 1, page_size: int = 10):
    """查询历史记录。

    GET /api/system/history — 获取历史记录列表
    GET /api/system/history/statistics — 获取统计数据
    """
    print("\n=== 9. 历史记录查询 ===")

    # 统计数据
    resp = requests.get(f"{base_url}/api/system/history/statistics", timeout=10)
    resp.raise_for_status()
    stats = resp.json()
    print(f"  统计: {stats}")

    # 历史记录列表
    resp = requests.get(
        f"{base_url}/api/system/history",
        params={"page": page, "page_size": page_size},
        timeout=10,
    )
    resp.raise_for_status()
    history = resp.json()
    records = history.get("records", [])
    print(f"  总记录: {history.get('total', 0)}, 第 {page} 页, 每页 {page_size} 条")
    for record in records[:5]:
        print(
            f"    [{record.get('id')}] {record.get('task_type')} | "
            f"{record.get('status')} | {record.get('input_file', 'N/A')[:50]}"
        )


def main():
    """主函数 — 演示完整的 API 调用流程。"""
    args = parse_args()
    base_url = args.base_url
    print(f"SeedVR2 API 示例 — 服务地址: {base_url}")

    # 1. 健康检查
    check_health(base_url)

    # 2. GPU 信息
    get_gpu_info(base_url)

    # 3. 加载模型
    load_model(base_url, size="3b", precision="fp16")

    # 4. 单文件修复（如果有测试文件）
    test_image = os.path.join(os.path.dirname(__file__), "sample.jpg")
    if os.path.exists(test_image):
        task_id = upload_and_restore(base_url, test_image)
        if task_id:
            # 6. SSE 进度监听
            listen_sse_progress(base_url, task_id, timeout=300)
            # 7. 获取结果
            get_task_result(base_url, task_id)
            # 8. 下载结果
            download_result(base_url, task_id)
    else:
        print(f"\n  (跳过单文件修复：未找到测试文件 {test_image})")
        print("  请放置一张图片到 examples/sample.jpg 以测试完整流程")

    # 5. 批量修复示例（注释掉，需要真实文件夹路径）
    # batch_restore(base_url, "/path/to/your/image/folder")

    # 9. 历史记录查询
    query_history(base_url)

    print("\n=== 示例完成 ===")


if __name__ == "__main__":
    main()
