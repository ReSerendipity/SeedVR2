# launcher/smoke_test.py
"""SeedVR2 启动器 - 冒烟测试（第 7 步）。

经应用 API 跑一次真实修复：健康检查 → 上传内置测试图 → 轮询任务 → 校验输出。
仅用 stdlib urllib 构造 multipart 上传，不引入 requests 依赖。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

SMOKE_TASK_TYPE = "image"
POLL_INTERVAL = 1.0
DEFAULT_TIMEOUT = 600


def build_multipart(filename: str, filedata: bytes, extra_fields: dict | None = None) -> tuple[bytes, str]:
    """构造 multipart/form-data 请求体（字段 file + 可选的 dit_model 等）。"""
    boundary = f"----seedvr2smoke{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for k, v in (extra_fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + filedata
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _json_post(url: str, data: bytes | None = None, content_type: str | None = None, timeout: int = 30) -> dict:
    req = Request(url, data=data, method="POST")
    if content_type:
        req.add_header("Content-Type", content_type)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_get(url: str, timeout: int = 30) -> dict:
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class SmokeTestResult:
    success: bool
    message: str
    output_path: str | None = None


def poll_until_done(app_base_url: str, task_id: str, timeout: int = DEFAULT_TIMEOUT) -> SmokeTestResult:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = _json_get(f"{app_base_url}/api/restore/{task_id}/result")
        status = res.get("data", {}).get("status")
        if status == "completed":
            out = res.get("data", {}).get("output_path")
            return SmokeTestResult(success=True, message="修复完成", output_path=out)
        if status in ("failed", "cancelled"):
            err = res.get("data", {}).get("error") or status
            return SmokeTestResult(success=False, message=f"任务{status}: {err}")
        time.sleep(POLL_INTERVAL)
    return SmokeTestResult(success=False, message="等待任务完成超时")


def run_smoke_test(app_base_url: str, test_image: str | Path, timeout: int = DEFAULT_TIMEOUT) -> SmokeTestResult:
    """等待应用就绪后上传测试图并跑一次修复。"""
    path = Path(test_image)
    try:
        # 1. 健康检查（等待应用起来）
        health_ok = False
        for _ in range(30):
            try:
                if _json_get(f"{app_base_url}/api/system/health", timeout=5).get("success"):
                    health_ok = True
                    break
            except Exception:
                time.sleep(1)
        if not health_ok:
            return SmokeTestResult(success=False, message="应用服务未就绪")

        # 2. 上传并创建任务
        body, content_type = build_multipart(
            filename=path.name,
            filedata=path.read_bytes(),
            extra_fields={"task_type": SMOKE_TASK_TYPE},
        )
        upload = _json_post(f"{app_base_url}/api/restore/", body, content_type, timeout=120)
        if not upload.get("success"):
            return SmokeTestResult(success=False, message=f"上传失败: {upload.get('error')}")
        task_id = upload["data"]["task_id"]

        # 3. 轮询结果
        return poll_until_done(app_base_url, task_id, timeout=timeout)
    except Exception as exc:  # 冒烟测试为边界，兜底报告
        return SmokeTestResult(success=False, message=f"冒烟测试异常: {exc}")
