# 安全与合规

## ⚠️ 网络绑定警告

SeedVR2 的 Web UI **默认仅绑定 `127.0.0.1`**（`config.yaml` 中 `server.host`），不对外暴露。
**严禁将 `server.host` 修改为 `0.0.0.0` 或公网 IP**，本应用不含用户认证与权限隔离机制，
直接暴露到公网将导致：

- 任意第三方调用推理 API 占用 GPU 资源
- 通过上传接口投递恶意文件
- 下载 outputs/ 与 uploads/ 目录内容

如需局域网共享，请在反向代理（Nginx/Caddy）后增加 Basic Auth，并启用 HTTPS。

## ©️ 归属权与版权

- **版权所有**: Copyright 2024-2026 ReSerendipity
- **开源协议**: [Apache License 2.0](https://github.com/ReSerendipity/SeedVR2-lite/blob/main/LICENSE)

**根据 Apache 2.0 协议第 4 条，任何再分发或衍生作品必须：**
1. 保留本项目的版权声明与 LICENSE 文件副本
2. 标注修改过的文件（声明已变更）
3. 保留所有 NOTICE 文件中的归属信息（如有）
4. 不得移除 UI 设置页、启动日志中展示的 "ReSerendipity" 版权归属

## 合规说明

使用本项目请遵守 [USER_AGREEMENT.md](https://github.com/ReSerendipity/SeedVR2-lite/blob/main/USER_AGREEMENT.md)。
模型权重（SeedVR/SeedVR2）为 Apache 2.0；FFmpeg 为本地开发依赖，不随仓库分发，由用户自行安装。

## ⚖️ 独立第三方声明

- 本项目是**独立的第三方社区工具**，基于字节跳动 Seed 团队与南洋理工大学 S-Lab 联合开源的
  **SeedVR2** 模型（Apache-2.0）构建，与字节跳动及其 Seed 团队**无隶属、赞助或官方合作关系**；
  对 "SeedVR2" 名称的使用仅为描述性引用，该名称与模型权重的知识产权归原作者所有。
- 本项目与 seedvr2.com / seedvr2.net / seedvr2.ai / seedvr2.app 等**付费商业站点无任何关系**；
  本项目完全免费开源，不提供积分、订阅等任何付费模式。
- 模型权重仅从官方来源下载：Hugging Face 官方仓库 `ByteDance-Seed/SeedVR2-3B` 与
  `ByteDance-Seed/SeedVR2-7B`（7B-Sharp 亦取自该官方 7B 仓库），请勿从未知来源获取权重。
