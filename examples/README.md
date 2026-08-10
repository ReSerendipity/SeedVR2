# SeedVR2 API 调用示例

本目录包含 SeedVR2 REST API 的调用示例代码，帮助开发者快速集成 SeedVR2 的视频与图像超分辨率修复能力。

## 文件说明

| 文件 | 语言 | 说明 |
|------|------|------|
| `api_example.py` | Python | 使用 `requests` 库调用全部 API 端点 |
| `api_example.js` | Node.js | 使用 `fetch` API 调用全部 API 端点（Node.js 18+） |

## 前置条件

1. **SeedVR2 服务已启动**：默认监听 `http://127.0.0.1:7870`
2. **模型已加载**：示例脚本会自动尝试加载 3B FP16 模型，也可通过 Web UI 手动加载
3. **Python 示例**：安装 `requests` 库
   ```bash
   pip install requests
   ```
4. **Node.js 示例**：需要 Node.js 18+（内置 `fetch` 和 `FormData`）

## 快速开始

### Python

```bash
# 确保服务已启动
python api_example.py

# 指定服务地址
python api_example.py --base-url http://192.168.1.100:7870
```

### Node.js

```bash
# 确保服务已启动
node api_example.js

# 指定服务地址
node api_example.js --base-url http://192.168.1.100:7870
```

## 示例覆盖的 API 端点

| # | API 端点 | 方法 | 说明 |
|---|----------|------|------|
| 1 | `/api/system/ping` | GET | 轻量级存活探针 |
| 2 | `/api/system/health` | GET | 详细系统健康检查 |
| 3 | `/api/system/gpu` | GET | GPU 硬件信息 |
| 4 | `/api/system/gpu/vram-estimate` | GET | VRAM 需求估算 |
| 5 | `/api/system/gpu/recommend-params` | GET | 参数推荐 |
| 6 | `/api/system/model/load` | POST | 加载模型 |
| 7 | `/api/system/model/status` | GET | 查询模型状态 |
| 8 | `/api/restore/` | POST | 上传文件创建修复任务 |
| 9 | `/api/restore/batch` | POST | 创建批量修复任务 |
| 10 | `/api/restore/{task_id}/progress` | GET | SSE 实时进度推送 |
| 11 | `/api/restore/{task_id}/result` | GET | 获取任务结果 |
| 12 | `/api/restore/{task_id}/download` | GET | 下载修复结果 |
| 13 | `/api/system/history` | GET | 查询历史记录 |
| 14 | `/api/system/history/statistics` | GET | 历史统计数据 |

## 测试文件

如需测试完整的单文件修复流程，请放置一张测试图片到本目录下，命名为 `sample.jpg`。

支持的图片格式：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.webp`
支持的视频格式：`.mp4`、`.avi`、`.mov`、`.mkv`、`.webm`、`.flv`、`.wmv`

## API 响应格式

SeedVR2 API 使用统一的 JSON 响应包装：

```json
{
    "success": true,
    "data": { ... },
    "error": null
}
```

错误响应：

```json
{
    "success": false,
    "data": null,
    "error": "错误描述"
}
```

或 HTTP 错误码带 `detail` 字段：

```json
{
    "detail": "错误描述"
}
```

## 常见参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_type` | string | `"auto"` | 任务类型：`auto`/`image`/`video` |
| `dit_model` | string | `"3b_fp16"` | 模型标识：`3b_fp16`/`3b_fp8`/`7b_fp16`/`7b_fp8`/`7b_sharp_fp16`/`7b_sharp_fp8` |
| `seed` | int | `42` | 随机种子（`-1` 为随机） |
| `resolution` | int | `2048` | 目标分辨率 |
| `max_resolution` | int | `0` | 最大分辨率限制（`0` 为不限制） |
| `fp8_enabled` | bool | `false` | 是否启用 FP8 量化 |
| `blocks_to_swap` | int | `0` | BlockSwap 交换块数（`0` 为禁用） |

## 更多信息

- [项目 README](../README.md)
- [部署文档](../docs/DEPLOYMENT.md)
- [架构文档](../docs/ARCHITECTURE.md)
- [安全策略](../SECURITY.md)
