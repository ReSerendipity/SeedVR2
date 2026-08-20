# API 参考

SeedVR2-lite 基于 FastAPI 提供 REST API，启动后可在 <http://127.0.0.1:7870/docs> 查看完整的 Swagger UI。

## 系统类

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/system/health` | 健康检查 |
| GET | `/api/system/gpu/status` | GPU 状态（利用率、显存、温度等） |
| GET | `/api/system/gpu/vram-estimate` | 估算指定参数下的显存需求 |
| GET | `/api/system/gpu/recommend-params` | 推荐参数组合（精度/BlockSwap/tile大小/风险等级） |
| GET | `/api/system/history` | 历史记录 |
| GET | `/api/system/metrics` | 系统指标 |
| GET | `/api/system/sse` | SSE 实时推送（GPU 状态 / 任务进度） |

## 修复类

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/restore/` | 单文件上传修复（图片 / 视频） |
| POST | `/api/restore/batch` | 文件夹批量修复 |
| GET | `/api/restore/task/{task_id}` | 查询任务状态与进度 |

## 任务管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tasks/checkpoint/recover` | 恢复未完成的批量任务 |
| GET | `/api/tasks/queue` | 任务队列状态 |

::: warning 网络绑定
Web UI 默认仅绑定 `127.0.0.1`（`config.yaml` 中 `server.host`），不对外暴露。
请勿将 `server.host` 修改为 `0.0.0.0` 或公网 IP，详见 [安全与合规](./security)。
:::
