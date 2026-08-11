# SeedVR2 性能监控计划

## 📊 监控指标
- **API 响应时间**: /api/system/health 端点的平均响应时间
- **最小/最大延迟**: 测量波动范围
- **服务可用性**: 健康检查是否成功

## 🚀 使用方法
`ash
# 1. 先启动 SeedVR2 服务
python -m uvicorn bin.integrated_app.app_server:app --host 127.0.0.1 --port 7870

# 2. 在新终端运行监控脚本
python perf_monitor.py
`

## 📁 输出位置
结果保存在 ./perf/results/benchmark_YYYYMMDD_HHMMSS.json

## 📋 执行建议
- **频率**: 每次部署前手动运行一次回归测试
- **基准对比**: 记录正常值作为参考（例如：平均响应 < 100ms）
- **告警阈值**: 如果超过 500ms 需调查原因

## ⚠️ 注意事项
- 监控脚本依赖服务正在运行
- 需要先安装依赖：pip install requests psutil
- 不需要设置定时任务，根据需要手动运行即可
- 建议在生产环境进行压力测试前先在开发环境验证
