# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-10

### Added

- **SeedVR2 扩散模型推理引擎**：支持 3B、7B、7B-Sharp 三种模型配置，含 FP16 与 FP8 精度
- **独立 Web UI**：基于 FastAPI + Jinja2 + Bootstrap 5 + htmx 的完整前端界面，无需 ComfyUI 依赖
- **MM-DiT 架构**：多模态 Diffusion Transformer，配合 Window Attention 与 RoPE 位置编码
- **Video VAE**：基于 SD3 架构的视频 VAE，支持时间分块与内存优化
- **GPU BlockSwap 优化**：推理时 GPU/CPU 间动态换入换出 Transformer 块，大幅降低显存需求
- **单文件与批量修复**：支持单文件上传修复和文件夹批量扫描修复，自动检测媒体类型
- **批量断点续跑**：Checkpoint 机制，每文件保存进度，崩溃恢复支持路径+大小+时间指纹去重
- **VRAM 预检与参数推荐**：估算公式 + FP16→FP8→BlockSwap 逐级回退，UI 集成 + API 端点
- **5 种语言国际化**：中文（zh）、繁体中文（zh-TW）、英文（en）、日文（ja）、法文（fr）
- **三层回退 i18n**：指定语言 → 英文 → key 本身，扁平键优先查找防止误判
- **SSE 实时进度推送**：Server-Sent Events 推送任务进度、模型状态变化、系统心跳
- **全局 SSE 事件总线**：发布/订阅模式，支持多客户端并发与会话隔离
- **SQLite 历史记录**：aiosqlite 异步驱动，支持分页、筛选、全文搜索
- **安全加固体系**：
  - 模型权重 SHA256 校验（加载前自动验证）
  - 核心模块启动自检（integrity_manifest.json）
  - 上传文件魔数校验（防伪装扩展名攻击）
  - PathGuard 白名单防护（防路径遍历攻击）
  - 输出数字水印（DCT 频域不可感知水印）
  - 权重加密支持
  - Secret Key 安全生成
- **完整测试体系**：
  - 40+ Python 单元/集成测试（pytest + pytest-asyncio）
  - 14 个 Playwright E2E 测试（含 POM 页面对象模型）
  - WCAG 无障碍测试 + 对比度测试
  - Locust 性能压力测试
  - 测试报告模板（Bug 报告 + 测试总结）
- **6 个 CI/CD Workflow**：ci、dependency-audit、e2e、gpg-signed-release、performance、security
- **GPG 签名发布**：GitHub Release 自动生成 SHA256SUMS + GPG 签名
- **8 个辅助脚本**：check_i18n_keys、cython_build、download_model、export_model、generate_lock、generate_integrity_manifest、pyarmor_pack、setup_winpython、smoke_test_security
- **Docker 支持**：Dockerfile + .dockerignore
- **跨平台安装/启动脚本**：Windows（install.bat + start.bat）、Linux/macOS（install.sh + start.sh）
- **依赖版本锁定**：requirements-lock.txt 支持 `--require-hashes` 哈希验证
- **代码质量工具链**：Ruff（lint + format）、Black、Mypy（渐进式类型检查）、Coverage（fail_under=65）
- **API 调用示例**：Python（requests）+ Node.js（fetch）示例代码
- **部署文档**：Linux systemd + Nginx 反向代理 + 多用户部署 + 备份策略
- **架构文档**：分层架构图 + 请求流程图 + 模块关系说明（Mermaid）
- **AGENTS.md**：AI 辅助开发指南
- **CODE_OF_CONDUCT.md**：Contributor Covenant v2.1 社区行为准则
- **GitHub Issue/PR 模板**：Bug 报告 + 功能请求 + PR 自查清单

### Security

- Web UI 默认仅绑定 `127.0.0.1`，不对外暴露
- pickle 格式 `.pt` checkpoint 优先使用 `weights_only=True` 加载，回退时打印安全告警
- 下载端点使用 PathGuard 白名单，仅允许 `outputs/` 和 `data/uploads/` 目录
- 扫描端点限制递归深度、文件总数、累计扫描大小三重防护
- `follow_symlinks=False` 防止符号链接绕过白名单
- 速率限制：上传接口 30 次/分钟
- CSRF 保护中间件
- Basic Auth 中间件（可选，通过环境变量配置）

## [Unreleased]

_后续版本变更记录将在此添加。_

---

[1.0.0]: https://github.com/ReSerendipity/SeedVR2-Toolkit/releases/tag/v1.0.0
