# SeedVR2 部署文档

本文档介绍如何在生产环境中部署 SeedVR2，涵盖 Linux systemd 服务、Nginx 反向代理、Docker 部署、多用户场景和备份策略。

> ⚠️ **安全警告**：SeedVR2 默认仅绑定 `127.0.0.1`，不含用户认证与权限隔离。如需对外提供服务，必须通过反向代理增加认证层。详见 [SECURITY.md](../SECURITY.md)。

---

## 一、服务器推荐配置

### GPU 型号与显存

| 模型 | 精度 | 最低显存 | 推荐 GPU |
|------|------|----------|----------|
| SeedVR2-3B | FP16 | 16 GB | RTX 4080 / RTX 3090 / A4000 |
| SeedVR2-3B | FP8 | 8 GB | RTX 4060 Ti 16GB / RTX 3080 |
| SeedVR2-7B | FP16 | 24 GB | RTX 4090 / A5000 / A6000 |
| SeedVR2-7B | FP8 | 12 GB | RTX 3080 12GB / RTX 4070 |
| SeedVR2-7B-Sharp | FP16 | 24 GB | RTX 4090 / A5000 / A6000 |
| SeedVR2-7B-Sharp | FP8 | 12 GB | RTX 3080 12GB / RTX 4070 |

### 系统资源

| 项目 | 最低要求 | 推荐 |
|------|----------|------|
| **CPU** | 4 核 | 8 核+ |
| **内存** | 16 GB | 32 GB+（视频处理需要大量内存缓冲） |
| **硬盘** | 50 GB SSD | 100 GB NVMe SSD（模型权重 + 输出文件） |
| **操作系统** | Ubuntu 22.04 / Debian 12 / CentOS 8+ | Ubuntu 24.04 LTS |
| **Python** | 3.12+ | 3.12.x |
| **CUDA** | 12.1+ | 12.4+ |
| **NVIDIA 驱动** | 535+ | 550+ |

---

## 二、Linux 部署

### 2.1 环境准备

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip \
    libgl1-mesa-glx libglib2.0-0 ffmpeg

# 验证 Python 版本
python3.12 --version  # 应输出 Python 3.12.x

# 验证 NVIDIA GPU
nvidia-smi  # 确认 GPU 可见且驱动正常
```

### 2.2 安装 SeedVR2

```bash
# 克隆仓库
git clone https://github.com/ReSerendipity/SeedVR2-Toolkit.git
cd SeedVR2

# 方式一：使用安装脚本（推荐）
chmod +x install.sh start.sh
./install.sh

# 方式二：手动安装
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

### 2.3 配置模型

```bash
# 将预训练模型放入 pretrained_models/ 目录
mkdir -p pretrained_models
# 从 ByteDance-Seed HuggingFace 下载模型权重
# https://huggingface.co/ByteDance-Seed
cp /path/to/seedvr2_ema_3b_fp16.safetensors pretrained_models/
cp /path/to/ema_vae_fp16.safetensors pretrained_models/
cp /path/to/pos_emb.pt pretrained_models/
cp /path/to/neg_emb.pt pretrained_models/
```

### 2.4 启动验证

```bash
# 启动应用
./start.sh
# 或手动启动
source .venv/bin/activate
python bin/clean_launch.py

# 验证服务
curl http://127.0.0.1:7870/api/system/ping
# 期望返回: {"status":"ok","version":"1.0.0","gpu_available":true}

# 运行引擎自检（可选）
python scripts/verify_engine.py
```

---

## 三、systemd 服务部署

### 3.1 创建服务文件

```bash
sudo tee /etc/systemd/system/seedvr2.service << 'EOF'
[Unit]
Description=SeedVR2 Video & Image Super-Resolution Toolkit
Documentation=https://github.com/ReSerendipity/SeedVR2-Toolkit
After=network.target

[Service]
Type=simple
User=seedvr2
Group=seedvr2
WorkingDirectory=/opt/seedvr2
Environment="KMP_DUPLICATE_LIB_OK=TRUE"
Environment="PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
Environment="HF_HUB_OFFLINE=1"
Environment="TRANSFORMERS_OFFLINE=1"
# 如需 Basic Auth，取消下行注释并设置密码
# Environment="SEEDVR2_AUTH_PASSWORD=your_secure_password"
ExecStart=/opt/seedvr2/.venv/bin/python /opt/seedvr2/bin/clean_launch.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# 资源限制
LimitNOFILE=65536
MemoryMax=infinity
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
```

### 3.2 创建服务用户

```bash
# 创建专用用户
sudo useradd -r -s /bin/false -d /opt/seedvr2 seedvr2

# 设置目录权限
sudo chown -R seedvr2:seedvr2 /opt/seedvr2
sudo chmod -R 750 /opt/seedvr2
```

### 3.3 启动服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start seedvr2

# 设置开机自启
sudo systemctl enable seedvr2

# 查看状态
sudo systemctl status seedvr2

# 查看日志
sudo journalctl -u seedvr2 -f
```

---

## 四、Nginx 反向代理

### 4.1 安装 Nginx

```bash
sudo apt-get install -y nginx
```

### 4.2 Nginx 配置

```bash
sudo tee /etc/nginx/sites-available/seedvr2 << 'EOF'
server {
    listen 80;
    server_name seedvr2.example.com;

    # 重定向到 HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name seedvr2.example.com;

    # SSL 证书（使用 Let's Encrypt 或自签名）
    ssl_certificate     /etc/ssl/certs/seedvr2.crt;
    ssl_certificate_key /etc/ssl/private/seedvr2.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Basic Auth（必选！SeedVR2 不含内置用户认证）
    auth_basic           "SeedVR2 Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd_seedvr2;

    # 上传文件大小限制（根据需要调整）
    client_max_body_size 500M;

    # 请求超时（视频处理可能需要较长时间）
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    # 反向代理到 SeedVR2
    location / {
        proxy_pass http://127.0.0.1:7870;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE 端点特殊配置（必须！否则进度推送会断开）
    location ~ ^/api/(restore/.*/progress|sse/events) {
        proxy_pass http://127.0.0.1:7870;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 关键配置
        proxy_buffering off;           # 禁用缓冲，实时推送
        proxy_cache off;               # 禁用缓存
        proxy_http_version 1.1;        # 使用 HTTP/1.1
        proxy_set_header Connection ""; # 清除 Connection 头
        chunked_transfer_encoding on;   # 启用分块传输
    }

    # 文件下载端点
    location ~ ^/api/restore/.*/download {
        proxy_pass http://127.0.0.1:7870;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering on;            # 下载使用缓冲
    }
}
EOF
```

### 4.3 配置 Basic Auth

```bash
# 安装 htpasswd 工具
sudo apt-get install -y apache2-utils

# 创建密码文件和用户
sudo htpasswd -c /etc/nginx/.htpasswd_seedvr2 admin
# 输入密码并确认

# 设置权限
sudo chown www-data:www-data /etc/nginx/.htpasswd_seedvr2
sudo chmod 640 /etc/nginx/.htpasswd_seedvr2
```

### 4.4 启用站点

```bash
# 启用站点
sudo ln -s /etc/nginx/sites-available/seedvr2 /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

### 4.5 HTTPS 证书（Let's Encrypt）

```bash
# 安装 Certbot
sudo apt-get install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d seedvr2.example.com

# 自动续期已由 certbot 配置，验证：
sudo certbot renew --dry-run
```

---

## 五、Docker 部署

### 5.1 构建镜像

```bash
docker build -t seedvr2-toolkit:latest .
```

### 5.2 运行容器

```bash
# 基本运行
docker run --gpus all -p 7870:7870 \
    -v $(pwd)/pretrained_models:/app/pretrained_models \
    -v $(pwd)/outputs:/app/outputs \
    -v $(pwd)/data:/app/data \
    --name seedvr2 \
    seedvr2:latest

# 带环境变量运行
docker run --gpus all -p 7870:7870 \
    -v $(pwd)/pretrained_models:/app/pretrained_models \
    -v $(pwd)/outputs:/app/outputs \
    -v $(pwd)/data:/app/data \
    -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    -e KMP_DUPLICATE_LIB_OK=TRUE \
    --name seedvr2 \
    --restart unless-stopped \
    seedvr2:latest
```

### 5.3 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  seedvr2:
    build: .
    image: seedvr2:latest
    container_name: seedvr2
    ports:
      - "127.0.0.1:7870:7870"  # 仅绑定本地
    volumes:
      - ./pretrained_models:/app/pretrained_models
      - ./outputs:/app/outputs
      - ./data:/app/data
      - ./config.yaml:/app/config.yaml
    environment:
      - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
      - KMP_DUPLICATE_LIB_OK=TRUE
      - HF_HUB_OFFLINE=1
      - TRANSFORMERS_OFFLINE=1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped
```

```bash
docker compose up -d
docker compose logs -f
```

---

## 六、多用户部署注意事项

### 6.1 并发数限制

SeedVR2 使用单 worker 顺序处理推理任务，避免 GPU OOM。多用户共享时需注意：

- **任务队列**：`config.yaml` 中 `runtime.task.queue_maxsize` 控制队列上限（默认 100）
- **SSE 超时**：`runtime.sse.max_duration_seconds` 控制单个 SSE 连接超时（默认 300 秒）
- **上传速率限制**：`runtime.security.rate_limit_per_minute` 限制上传频率（默认 30 次/分钟）

```yaml
# 多用户场景推荐配置
runtime:
  task:
    queue_maxsize: 50          # 适当降低队列上限
    max_timeout_seconds: 7200  # 长视频任务超时延长到 2 小时
  sse:
    max_duration_seconds: 600  # SSE 超时延长到 10 分钟
  security:
    rate_limit_per_minute: 15  # 降低速率限制
```

### 6.2 用户隔离

- 每个用户使用独立的 Nginx Basic Auth 账号
- **输出目录共享**：所有用户的输出文件存储在同一个 `outputs/` 目录，通过历史记录区分
- **上传隔离**：上传文件存储在 `data/uploads/image/` 和 `data/uploads/video/` 下
- **会话隔离**：SSE 事件总线支持 `session_id` 参数实现事件过滤

### 6.3 进程守护

推荐使用 systemd 或 Docker 的 `--restart` 策略确保服务自动恢复：

```bash
# systemd 自动重启（已在服务文件中配置）
Restart=on-failure
RestartSec=10

# Docker 自动重启
docker run --restart unless-stopped ...
```

---

## 七、备份策略

### 7.1 需要备份的内容

| 内容 | 路径 | 重要性 | 频率 |
|------|------|--------|------|
| 历史数据库 | `data/history.db` | 高 | 每日 |
| 输出文件 | `outputs/` | 高 | 每日 |
| 上传文件 | `data/uploads/` | 中 | 每日 |
| 应用配置 | `config.yaml` | 高 | 变更时 |
| Checkpoint 文件 | `data/checkpoints/` | 低 | 每周 |
| 模型权重 | `pretrained_models/` | 低 | 变更时（可从源头重新下载） |

### 7.2 自动备份脚本

使用项目内置的备份脚本：

```bash
# Linux/macOS
chmod +x scripts/backup-db.sh
./scripts/backup-db.sh

# Windows
scripts\backup-db.bat

# 配置 cron 定时备份（每天凌晨 3 点）
crontab -e
# 添加：
0 3 * * * /opt/seedvr2/scripts/backup-db.sh >> /var/log/seedvr2-backup.log 2>&1
```

### 7.3 备份存储策略

- **本地备份**：保留最近 7 天的备份
- **远程备份**：每周同步到远程存储（S3 / OSS / NAS）
- **备份验证**：每月恢复一次备份到测试环境验证完整性

```bash
# 示例：使用 rsync 同步到远程 NAS
rsync -avz --delete /opt/seedvr2/backups/ backup@nas:/backups/seedvr2/
```

---

## 八、监控与运维

### 8.1 健康检查

```bash
# 轻量探针（适合负载均衡器）
curl http://127.0.0.1:7870/api/system/ping

# 详细健康检查
curl http://127.0.0.1:7870/api/system/health

# GPU 状态
curl http://127.0.0.1:7870/api/system/gpu

# 性能指标
curl http://127.0.0.1:7870/api/system/metrics
```

### 8.2 日志管理

```bash
# 实时查看应用日志
tail -f /opt/seedvr2/logs/app.log

# systemd 日志
journalctl -u seedvr2 -f

# Nginx 访问日志
tail -f /var/log/nginx/access.log

# Nginx 错误日志
tail -f /var/log/nginx/error.log
```

### 8.3 常见运维操作

```bash
# 重启服务
sudo systemctl restart seedvr2

# 加载新模型
curl -X POST http://127.0.0.1:7870/api/system/model/load \
    -H "Content-Type: application/json" \
    -d '{"size": "7b", "precision": "fp8"}'

# 卸载模型释放显存
curl -X POST http://127.0.0.1:7870/api/system/model/unload

# 清理失败的历史记录
curl -X DELETE "http://127.0.0.1:7870/api/system/history?status=failed"
```

---

## 九、性能优化

### 9.1 显存优化

```yaml
# config.yaml 推荐配置（8GB 显存 / 3B 模型）
inference:
  fp8_enabled: true           # 启用 FP8 量化
  blocks_to_swap: 16          # BlockSwap 交换块数
  vae_tile_size: 512          # VAE 分块大小
  vae_overlap: 128            # VAE 重叠区域
  temporal_segment_size: 5    # 视频时间分段
```

### 9.2 磁盘 I/O 优化

- 使用 NVMe SSD 存放模型权重和输出文件
- 将 `data/uploads/` 和 `outputs/` 放在不同磁盘减少 I/O 竞争
- 定期清理过期输出文件

### 9.3 网络优化

- 启用 Nginx gzip 压缩（静态资源）
- 对 SSE 端点禁用缓冲（已在 Nginx 配置中设置）
- 上传大文件时启用分块传输

---

*文档更新时间：2026-08-10*
