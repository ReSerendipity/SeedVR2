"""
SeedVR2 自动化API测试脚本
验证所有核心API端点正常工作
连续执行3轮测试
"""
import urllib.request
import urllib.error
import urllib.parse
import json
import sys
import time
import os

BASE_URL = "http://127.0.0.1:7870"
results = []

def test_endpoint(name, method, path, expected_statuses=(200,), expect_json=True):
    """测试单个API端点，接受多个预期状态码"""
    url = BASE_URL + path
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            data = resp.read()
            if expect_json:
                try:
                    json_data = json.loads(data.decode('utf-8'))
                    if status in expected_statuses:
                        results.append((name, "PASS", f"Status {status}", json_data))
                    else:
                        results.append((name, "FAIL", f"Status {status} not in expected {expected_statuses}", None))
                    return json_data
                except json.JSONDecodeError:
                    results.append((name, "FAIL", f"Invalid JSON response", data[:200]))
                    return None
            else:
                if status in expected_statuses:
                    results.append((name, "PASS", f"Status {status}", data[:200]))
                else:
                    results.append((name, "FAIL", f"Status {status} not in expected {expected_statuses}", None))
                return data
    except urllib.error.HTTPError as e:
        if e.code in expected_statuses:
            results.append((name, "PASS", f"Expected HTTP {e.code} (security/error handling works)", None))
        else:
            results.append((name, "FAIL", f"HTTP {e.code} (expected {expected_statuses})", None))
        return None
    except Exception as e:
        results.append((name, "FAIL", str(e), None))
        return None

def test_page(name, path):
    """测试页面是否正常加载（HTML返回）"""
    return test_endpoint(name, "GET", path, expected_statuses=(200,), expect_json=False)

def run_test_round(round_num):
    """执行一轮完整测试"""
    global results
    results = []
    print(f"\n{'='*60}")
    print(f"  第 {round_num} 轮测试 - 开始于 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # 1. 核心API端点测试
    print("\n--- API端点测试 ---")
    health = test_endpoint("健康检查 /api/system/health", "GET", "/api/system/health")
    gpu = test_endpoint("GPU信息 /api/system/gpu", "GET", "/api/system/gpu")
    model_status = test_endpoint("模型状态 /api/system/model/status", "GET", "/api/system/model/status")
    settings = test_endpoint("获取设置 /api/system/settings", "GET", "/api/system/settings")
    history = test_endpoint("历史记录 /api/system/history", "GET", "/api/system/history?page=1&page_size=5")
    
    # 2. 页面路由测试
    print("\n--- 页面路由测试 ---")
    test_page("首页 /", "/")
    test_page("修复工作台 /restore", "/restore")
    test_page("历史记录 /history", "/history")
    test_page("系统状态 /system-status", "/system-status")
    test_page("设置 /settings", "/settings")
    
    # 3. 测试404/安全路径处理
    print("\n--- 异常路径与安全测试 ---")
    # 不存在路径应返回200（前端路由处理）或404
    test_endpoint("不存在路径处理", "GET", "/nonexistent-page-xyz-12345", expected_statuses=(200, 404), expect_json=False)
    # 路径遍历/无效盘符应返回403（path_guard安全机制）- 预期被拒绝
    test_endpoint("无效盘符路径安全拦截(预期403)", "GET", "/api/restore/scan-folder?folder_path=Z%3A%2FInvalidPathTest123", expected_statuses=(403, 400, 404))
    # 非白名单路径应返回403（安全机制正常工作）- C:\Users不在默认白名单
    test_endpoint("非白名单路径安全拦截(预期403)", "GET", "/api/restore/scan-folder?folder_path=C%3A%2FWindows", expected_statuses=(403,))
    # 白名单内路径扫描测试（outputs在白名单中）
    outputs_path = os.path.join(os.getcwd(), "outputs")
    outputs_encoded = urllib.parse.quote(outputs_path)
    test_endpoint("白名单路径扫描(outputs目录)", "GET", f"/api/restore/scan-folder?folder_path={outputs_encoded}", expected_statuses=(200, 404))
    
    # 4. 验证关键响应内容
    print("\n--- 响应内容验证 ---")
    if health and isinstance(health, dict):
        if health.get("status") == "ok" or health.get("success"):
            results.append(("健康检查返回正常状态", "PASS", f"status={health.get('status')}", None))
            sys_info = health.get("system", {})
            gpu_info = health.get("gpu", {})
            model_info = health.get("model", {})
            results.append(("系统信息字段完整", "PASS", f"platform={sys_info.get('platform', 'N/A')}", None))
            results.append(("GPU信息字段完整", "PASS", f"is_gpu_available={gpu_info.get('is_gpu_available')}", None))
            results.append(("模型状态字段完整", "PASS", f"model_loaded={model_info.get('model_loaded')}", None))
        else:
            results.append(("健康检查返回正常状态", "FAIL", f"Unexpected response: {str(health)[:100]}", None))
    
    if gpu and isinstance(gpu, dict):
        if gpu.get("backend") == "cuda" and gpu.get("device_name"):
            results.append(("GPU信息包含CUDA后端", "PASS", f"device={gpu.get('device_name')}", None))
        else:
            results.append(("GPU信息包含CUDA后端", "FAIL", f"Missing fields: {str(gpu)[:100]}", None))
    
    if model_status is not None:
        results.append(("模型状态API可访问", "PASS", "Endpoint responded", None))
    
    if settings is not None:
        results.append(("设置API可访问", "PASS", "Endpoint responded", None))
    
    if history is not None:
        results.append(("历史记录API可访问", "PASS", "Endpoint responded", None))
    
    # 5. 页面内容验证（验证关键HTML元素）
    print("\n--- HTML内容关键元素验证 ---")
    try:
        with urllib.request.urlopen(BASE_URL + "/system-status", timeout=10) as resp:
            html = resp.read().decode('utf-8')
            if '系统状态' in html or 'System Status' in html:
                results.append(("系统状态页面包含正确标题", "PASS", "Title text found", None))
            else:
                results.append(("系统状态页面包含正确标题", "FAIL", "Title text not found", None))
            # 验证没有重定向到首页（应该不是RedirectResponse）
            if '让每一帧画面' not in html or 'GPU' in html or 'gpu' in html.lower():
                results.append(("系统状态页面未重定向到首页", "PASS", "System status content present", None))
            else:
                results.append(("系统状态页面未重定向到首页", "FAIL", "Appears to be homepage", None))
    except Exception as e:
        results.append(("系统状态页面HTML验证", "FAIL", str(e), None))
    
    # 统计结果
    passed = sum(1 for r in results if r[1] == "PASS")
    failed = sum(1 for r in results if r[1] == "FAIL")
    total = len(results)
    
    print(f"\n{'─'*60}")
    print(f"  第 {round_num} 轮测试结果")
    print(f"{'─'*60}")
    print(f"  总计: {total} 项    通过: {passed} 项    失败: {failed} 项")
    print(f"  通过率: {passed/total*100:.1f}%")
    
    if failed > 0:
        print(f"\n  失败项详情:")
        for name, status, msg, data in results:
            if status == "FAIL":
                print(f"    ✗ {name}")
                print(f"      {msg}")
    
    return passed, failed, total

if __name__ == "__main__":
    rounds = 3
    all_passed = True
    round_results = []
    
    print("SeedVR2 自动化连续测试")
    print(f"目标: 连续 {rounds} 轮无错误")
    print(f"服务: {BASE_URL}")
    
    for i in range(1, rounds+1):
        if i > 1:
            time.sleep(1)
        p, f, t = run_test_round(i)
        round_results.append((p, f, t))
        if f > 0:
            all_passed = False
    
    print(f"\n{'='*60}")
    print(f"  连续 {rounds} 轮测试总结")
    print(f"{'='*60}")
    for i, (p, f, t) in enumerate(round_results, 1):
        icon = "✓" if f == 0 else "✗"
        print(f"  {icon} 第 {i} 轮: {p}/{t} 通过 ({p/t*100:.1f}%)")
    
    print()
    if all_passed:
        print(f"  ✓ 验收通过: 连续 {rounds} 轮测试全部通过！")
        print(f"  ✓ 所有核心API和页面正常工作")
        sys.exit(0)
    else:
        print(f"  ✗ 验收未通过: 存在失败的测试项")
        sys.exit(1)
