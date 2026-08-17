# SeedVR2 性能基准测试指南

## 📋 概述

`perf/benchmark/bench_restore_api.py` 提供端到端的修复 API 性能测量，包括：
- **submit**: 文件上传 + 任务创建耗时
- **processing**: 后台推理处理耗时（**核心对比指标**）
- **total**: 总耗时（submit + processing）

## 🚀 快速开始

### 前置条件

1. **启动 SeedVR2 服务**:
   ```bash
   # Windows
   python bin/clean_launch.py
   
   # 或使用 uvicorn
   uvicorn bin.integrated_app.app_server:app --host 127.0.0.1 --port 7870
   ```

2. **准备测试文件**:
   - 图片：任意 JPG/PNG，建议 512×512 ~ 2048×2048
   - 视频：MP4/AVI，建议 1~5 秒，分辨率与目标输出一致

### 单文件基准测试

```bash
# 基础用法（默认参数）
python perf/benchmark/bench_restore_api.py \
    --file "test-assets/sample.jpg" \
    --label "baseline_test"

# 指定模型精度
python perf/benchmark/bench_restore_api.py \
    --file "test-assets/sample.jpg" \
    --label "fp16_vs_fp8" \
    --dit-model 3b_fp16 \
    --task-type image \
    --resolution 1024

# 视频修复基准
python perf/benchmark/bench_restore_api.py \
    --file "test-assets/sample.mp4" \
    --label "video_baseline" \
    --task-type video \
    --dit-model 3b_fp16
```

### 对比实验（推荐流程）

```bash
# 1. FP16 vs FP8 对比
echo "=== FP16 ==="
python perf/benchmark/bench_restore_api.py \
    --file "sample.jpg" --label "fp16" --dit-model 3b_fp16

echo "=== FP8 ==="
python perf/benchmark/bench_restore_api.py \
    --file "sample.jpg" --label "fp8" --dit-model 3b_fp8

# 2. torch.compile 开启前后对比
# 先配置 config.yaml: inference.torch_compile.enabled = true
echo "=== Before compile (first run) ==="
python perf/benchmark/bench_restore_api.py \
    --file "sample.jpg" --label "first_run"

echo "=== After compile (steady state) ==="
python perf/benchmark/bench_restore_api.py \
    --file "sample.jpg" --label "second_run"
```

## 📊 结果解读

### 典型输出

```
[baseline_test] task_id=abc123 submit=2.3s
[baseline_test] status=completed processing=38.5s total=40.8s
```

| 指标 | 含义 | 参考值（图片 1024×1024） |
|------|------|------------------------|
| **submit** | 上传 + 建任务 | < 3s（取决于文件大小） |
| **processing** | 推理耗时 | FP16: ~35-45s<br>FP8: ~30-40s |
| **total** | 总耗时 | submit + processing |

### ⚡ 性能调优参考

#### torch.compile 影响

| 场景 | 首次推理 | 稳态推理 | 提升 |
|------|---------|---------|------|
| 无 torch.compile | ~45s | ~45s | - |
| 有 torch.compile | ~110s（含编译） | ~30-35s | **~22%** |

**注意**: 首次运行包含 inductor 编译时间（~70-110s），应以第二次运行（稳态）为基准对比。

#### 显存优化效果（12GB GPU）

| 配置 | processing 耗时 | 备注 |
|------|---------------|------|
| FP16 | ~38s | 基础配置 |
| FP8 | ~35s | ~7% 提速，显存占用下降 |
| blocks_to_swap=2 | ~45s | CPU 换页开销增加 |
| blocks_to_swap=4 | ~50s | 更多 CPU 换页 |

## 🔄 自动化测试

### 批量对比脚本

```bash
#!/bin/bash
# perf/benchmark/run_batch_bench.sh

FILES=("sample_512.jpg" "sample_1024.jpg" "sample_2048.jpg")
MODELS=("3b_fp16" "3b_fp8")

for file in "${FILES[@]}"; do
    for model in "${MODELS[@]}"; do
        echo "=== Testing $file with $model ==="
        python perf/benchmark/bench_restore_api.py \
            --file "test-assets/$file" \
            --label "${file}_${model}" \
            --dit-model "$model" \
            --resolution "${file%%_*}" \
            2>&1 | tee "outputs/bench-${file%%.*}-${model}.log"
    done
done
```

### CI 集成建议

在 `.github/workflows/performance.yml` 中：

```yaml
- name: Run benchmark (short)
  run: |
    python perf/benchmark/bench_restore_api.py \
      --file "tests/test-assets/images/sample.png" \
      --label "ci_baseline" \
      --dit-model 3b_fp16 \
      --resolution 512
  # 预期 processing < 60s（超时阈值设置）
```

## 📈 趋势追踪

建议每周固定时间运行一次完整基准：

```bash
# 周一上午自动运行（crontab 示例）
0 9 * * 1 cd /path/to/SeedVR2 && \
    python perf/benchmark/bench_restore_api.py \
        --file "weekly_baseline.jpg" \
        --label "weekly_$(date +%Y%m%d)" >> logs/benchmark.log
```

结果存档到 `outputs/benchmark-history/`，便于观察长期趋势。

## 🐛 常见问题

### Q1: processing 耗时异常高？

**可能原因**:
1. CPU 换页过多（blocks_to_swap 设置过大）
2. GPU 驱动版本过旧
3. 其他进程占用 GPU

**诊断**:
```python
# 检查 GPU 状态
nvidia-smi -q | grep -E "Memory|Utilization"

# 查看实时日志
python -c "from bin.integrated_app.config import load_config; print(load_config()['inference'])"
```

### Q2: 首次运行特别慢？

**正常现象**: torch.compile 的 inductor 第一次遇到 DiT/VAE 图时会编译，耗时约 70-110s。**应忽略首次数据，用第二次为准**。

### Q3: 如何验证性能改进有效？

**标准流程**:
1. 同硬件、同测试文件、同参数（仅改待测项）
2. 各跑至少 2 次（跳过首次编译影响）
3. processing 耗时差异 > 5% 才算显著改进
4. 记录配置快照（config.yaml、CUDA 版本、PyTorch 版本）

## 📁 相关文档

- [AGENTS.md §11 #12](../../AGENTS.md): torch.compile 缓存目录持久化坑点
- [AGENTS.md §11 #11](../../AGENTS.md): Blackwell 架构 SDPA 内核可用性限制
- `config.yaml`: inference 相关配置项说明
- `docs/OPTIMIZATION_GUIDE.md`: 详细优化方案文档

---

**维护者**: SeedVR2 Team  
**最后更新**: 2026-08-17  
**版本**: v1.0.0
