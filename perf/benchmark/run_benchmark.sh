#!/usr/bin/env bash
# SeedVR2 性能基准测试一键脚本
# 
# 用法:
#   ./run_benchmark.sh <test_image_or_video> [label]
#
# 前提条件:
#   1. 已启动 SeedVR2 服务：python bin/clean_launch.py
#   2. 测试文件存在且可访问
#
# 输出:
#   - 提交耗时 (submit)
#   - 处理耗时 (processing) ← 核心指标
#   - 总耗时 (total)
#   - 结果保存到 outputs/bench-<timestamp>.json
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_FILE="$1"
LABEL="${2:-$(basename "$TEST_FILE")}"

if [ ! -f "$TEST_FILE" ]; then
    echo "[ERROR] 测试文件不存在：$TEST_FILE"
    exit 1
fi

echo "=========================================="
echo "SeedVR2 性能基准测试"
echo "=========================================="
echo "文件：$TEST_FILE"
echo "标签：$LABEL"
echo "时间：$(date -Iseconds)"
echo ""

# 记录起始状态
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="$PROJECT_ROOT/outputs/bench-$TIMESTAMP.json"
mkdir -p "$PROJECT_ROOT/outputs"

# 运行基准测试
python "$SCRIPT_DIR/bench_restore_api.py" \
    --file "$TEST_FILE" \
    --label "$LABEL" \
    --task-type image \
    --resolution 1024 \
    --param dit_model=3b_fp16 \
    --param vae_model=vae_ema_fp16 2>&1 | tee "$OUTPUT_FILE.log"

echo ""
echo "=========================================="
echo "结果日志：$OUTPUT_FILE.log"
echo "=========================================="
