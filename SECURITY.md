# Security Policy

## Supported Versions

SeedVR2 当前处于 v1.0.0 初始发布阶段。安全修复仅适用于以下版本：

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

我们非常重视 SeedVR2 的安全问题。如果您发现安全漏洞，请**不要**通过公开 Issue 报告，而是按照以下流程私下披露：

### 报告渠道

- **邮箱**：请发送邮件至 `security@reserendipity.dev`（加密通信优先）
- **GitHub Security Advisory**：推荐使用 GitHub 的 [私密漏洞报告功能](https://github.com/ReSerendipity/SeedVR2-lite/security/advisories/new)
- **邮件主题**：`[SECURITY] SeedVR2 - <简短描述>`

### 报告内容

为帮助我们快速定位和修复问题，请在报告中包含：

1. **漏洞描述**：问题的清晰描述及其影响范围
2. **复现步骤**：详细的复现方法（最小化 PoC 优先）
3. **影响评估**：可能的攻击场景和受影响的用户范围
4. **环境信息**：操作系统、Python 版本、GPU 型号、SeedVR2 版本
5. **建议修复方案**（可选）

### 响应时间承诺

| 阶段 | 时间承诺 |
|------|----------|
| 确认收到报告 | 24 小时内 |
| 初步评估与分类 | 3 个工作日内 |
| 修复方案制定 | 7 天内（严重漏洞优先 48 小时内） |
| 修复版本发布 | 30 天内（严重漏洞 7 天内） |

## Disclosure Process

1. **私下报告**：漏洞通过上述渠道私下报告给维护团队
2. **确认与评估**：维护团队确认漏洞并评估严重程度
3. **修复开发**：在私有分支中开发修复方案
4. **修复发布**：发布修复版本，并在 Release Notes 中说明安全问题
5. **公开公告**：修复版本发布后，通过 GitHub Security Advisory 公开披露漏洞详情
6. **致谢**：在征得报告者同意后，在公告中致谢漏洞报告者

## Security Measures

SeedVR2 已实施以下安全措施：

### 模型与文件安全

- **模型权重 SHA256 校验**：加载前自动验证权重文件完整性
- **核心模块启动自检**：`integrity_manifest.json` 记录核心安全模块哈希，启动时自动比对
- **上传文件魔数校验**：防止伪装扩展名上传恶意文件
- **pickle 安全加载**：`.pt` checkpoint 优先使用 `weights_only=True`，回退时打印安全告警

### 路径与访问控制

- **PathGuard 白名单**：下载和扫描端点仅允许 `outputs/` 和 `data/uploads/` 目录
- **路径遍历防护**：拒绝包含 `..` 的路径，使用 `realpath()` 解析符号链接
- **速率限制**：上传接口 30 次/分钟
- **网络绑定**：默认仅绑定 `127.0.0.1`，不对外暴露

### 输出保护

- **内容溯源**：推理输出自动嵌入不可感知的来源标识，可溯源到 SeedVR2
- **GPG 签名**：GitHub Release 自动生成 SHA256SUMS + GPG 签名

### 依赖安全

- **依赖版本锁定**：`requirements-lock.txt` 固定所有依赖版本
- **哈希验证**：支持 `--require-hashes` 哈希验证
- **依赖审计 CI**：自动化依赖漏洞扫描 workflow

## ⚠️ Important Security Notes

### 网络绑定警告

SeedVR2 的 Web UI **默认仅绑定 `127.0.0.1`**。**严禁将 `server.host` 修改为 `0.0.0.0` 或公网 IP**。本应用不含用户认证与权限隔离机制，直接暴露到公网将导致：
- 任意第三方调用推理 API 占用 GPU 资源
- 通过上传接口投递恶意文件
- 下载 `outputs/` 与 `data/uploads/` 目录内容

如需局域网共享，请在反向代理（Nginx/Caddy）后增加 Basic Auth，并启用 HTTPS。详见 [部署文档](docs/DEPLOYMENT.md)。

### 模型来源

- 所有模型权重请从官方可信来源下载（ByteDance-Seed HuggingFace 组织）
- 切勿加载来源不明的 `.safetensors`、`.pt`、`.bin` 文件

---

版权所有 © 2024-2026 ReSerendipity. 本安全政策遵循 Apache License 2.0。
