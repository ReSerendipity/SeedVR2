#!/usr/bin/env bash
# SeedVR2 数据库备份脚本 (Linux/macOS)
# 备份 SQLite 历史数据库 + 输出目录 + 上传目录
#
# Usage:
#   ./scripts/backup-db.sh [--output /path/to/backup]
#
# 默认备份到 backups/ 目录，保留最近 7 天的备份。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 备份输出目录
BACKUP_DIR="${1:-backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/seedvr2_backup_$TIMESTAMP"

echo "============================================"
echo "  SeedVR2 数据库备份"
echo "============================================"
echo "  项目路径: $PROJECT_ROOT"
echo "  备份路径: $BACKUP_PATH"
echo "  时间戳:   $TIMESTAMP"
echo ""

# 创建备份目录
mkdir -p "$BACKUP_PATH"

# 1. 备份 SQLite 数据库
echo "[1/4] 备份 SQLite 历史数据库..."
DB_PATH="data/history.db"
if [ -f "$DB_PATH" ]; then
    # 使用 SQLite 的 .backup 命令确保一致性
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH/history.db'"
        echo "  [OK] history.db 已备份 ($(du -h "$BACKUP_PATH/history.db" | cut -f1))"
    else
        # 没有 sqlite3 命令，直接复制（可能有一致性风险）
        cp "$DB_PATH" "$BACKUP_PATH/history.db"
        echo "  [OK] history.db 已复制 ($(du -h "$BACKUP_PATH/history.db" | cut -f1))"
        echo "  [WARN] 建议安装 sqlite3 以确保备份一致性"
    fi
else
    echo "  [SKIP] history.db 不存在"
fi

# 2. 备份配置文件
echo "[2/4] 备份配置文件..."
if [ -f "config.yaml" ]; then
    cp config.yaml "$BACKUP_PATH/"
    echo "  [OK] config.yaml 已备份"
fi
if [ -f ".env" ]; then
    cp .env "$BACKUP_PATH/.env.backup"
    echo "  [OK] .env 已备份"
fi

# 3. 备份输出目录
echo "[3/4] 备份输出目录..."
if [ -d "outputs" ]; then
    cp -r outputs "$BACKUP_PATH/outputs"
    OUTPUT_SIZE=$(du -sh "$BACKUP_PATH/outputs" | cut -f1)
    echo "  [OK] outputs/ 已备份 ($OUTPUT_SIZE)"
else
    echo "  [SKIP] outputs/ 不存在"
fi

# 4. 备份上传目录
echo "[4/4] 备份上传目录..."
if [ -d "data/uploads" ]; then
    cp -r data/uploads "$BACKUP_PATH/uploads"
    UPLOAD_SIZE=$(du -sh "$BACKUP_PATH/uploads" | cut -f1)
    echo "  [OK] data/uploads/ 已备份 ($UPLOAD_SIZE)"
else
    echo "  [SKIP] data/uploads/ 不存在"
fi

# 压缩备份
echo ""
echo "[压缩] 创建 tar.gz 压缩包..."
ARCHIVE="$BACKUP_DIR/seedvr2_backup_$TIMESTAMP.tar.gz"
tar -czf "$ARCHIVE" -C "$BACKUP_DIR" "seedvr2_backup_$TIMESTAMP"
ARCHIVE_SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "  [OK] 压缩包: $ARCHIVE ($ARCHIVE_SIZE)"

# 清理未压缩的临时目录
rm -rf "$BACKUP_PATH"

# 清理旧备份（保留最近 7 天）
echo ""
echo "[清理] 删除 7 天前的旧备份..."
OLD_COUNT=$(find "$BACKUP_DIR" -name "seedvr2_backup_*.tar.gz" -mtime +7 | wc -l)
if [ "$OLD_COUNT" -gt 0 ]; then
    find "$BACKUP_DIR" -name "seedvr2_backup_*.tar.gz" -mtime +7 -delete
    echo "  [OK] 已删除 $OLD_COUNT 个旧备份"
else
    echo "  [INFO] 没有需要清理的旧备份"
fi

echo ""
echo "============================================"
echo "  备份完成！"
echo "  文件: $ARCHIVE"
echo "  大小: $ARCHIVE_SIZE"
echo "============================================"
