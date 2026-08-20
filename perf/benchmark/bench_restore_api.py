#!/usr/bin/env python3
"""SeedVR2 修复耗时基准脚本（走真实 HTTP API）。

用法：
    python perf/benchmark/bench_restore_api.py --file <media> --label <名字> \
        [--dit-model 3b_fp16|3b_fp8] [--task-type image|video] [--resolution 1024] \
        [--param key=value ...]

说明：
    1. 需要先在本地启动 SeedVR2 服务（app/clean_launch.py）。
    2. 通过 multipart/form-data 上传文件 + 参数，POST /api/restore/。
    3. 轮询 /api/restore/{task_id}/result 直到终态，打印：
       - submit: 上传+建任务耗时
       - processing: 后台推理耗时（本文中对比的核心指标）
       - total: 总耗时
    4. 自动处理 CSRF（Double Submit Cookie：先 GET 拿 cookie，POST 带 X-CSRF-Token）。
    5. 首次运行同一模型会触发 torch.compile（若开启），耗时偏大属正常，应以第 2 次（稳态）为准。
"""

import argparse
import time

import requests

BASE = "http://127.0.0.1:7870"
TERMINAL = ("completed", "failed", "cancelled", "timeout")


def bench(file_path: str, label: str, form: dict) -> float | None:
    s = requests.Session()
    s.get(f"{BASE}/", timeout=30)  # 拿 csrf_token cookie
    csrf = s.cookies.get("csrf_token", "")
    headers = {"X-CSRF-Token": csrf} if csrf else {}

    with open(file_path, "rb") as f:
        fname = file_path.rsplit("\\", 1)[-1]
        files = {"file": (fname, f, "application/octet-stream")}
        t0 = time.time()
        resp = s.post(f"{BASE}/api/restore/", files=files, data=form, headers=headers, timeout=30)
        t1 = time.time()
        if resp.status_code != 200:
            print(f"[{label}] POST failed: {resp.status_code} {resp.text[:300]}")
            return None
        task_id = resp.json()["data"]["task_id"]
        print(f"[{label}] task_id={task_id} submit={t1 - t0:.1f}s")

    t_submit = t1 - t0
    t_start = time.time()
    while True:
        r = s.get(f"{BASE}/api/restore/{task_id}/result", timeout=30)
        j = r.json()
        data = j.get("data", {})
        st = data.get("status") or j.get("status")
        if st in TERMINAL:
            elapsed = time.time() - t_start
            print(f"[{label}] status={st} processing={elapsed:.1f}s total={t_submit + elapsed:.1f}s")
            if st == "failed":
                print(f"[{label}] error: {data.get('error')}")
            return elapsed
        time.sleep(2.0)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", required=True, help="待修复的图片或视频路径")
    p.add_argument("--label", default="run", help="本次运行标签")
    p.add_argument("--dit-model", default="3b_fp16")
    p.add_argument("--task-type", default="image", choices=["image", "video"])
    p.add_argument("--resolution", type=int, default=1024)
    p.add_argument("--param", action="append", default=[], help="额外表单字段 key=value，可多次")
    args = p.parse_args()

    form = {
        "task_type": args.task_type,
        "dit_model": args.dit_model,
        "resolution": str(args.resolution),
        "max_resolution": "0",
        "blocks_to_swap": "32",
        "batch_size": "5",
    }
    for kv in args.param:
        if "=" in kv:
            k, v = kv.split("=", 1)
            form[k] = v

    bench(args.file, args.label, form)


if __name__ == "__main__":
    main()
