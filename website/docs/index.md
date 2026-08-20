---
layout: home

hero:
  name: SeedVR2-lite
  text: 视频与图像超分辨率修复工具箱
  tagline: 基于 SeedVR2 扩散模型 · 独立运行 · 一键修复 · 无需 ComfyUI
  image:
    src: /SeedVR2-lite/docs/logo.svg
    alt: SeedVR2-lite
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quickstart
    - theme: alt
      text: 在线模拟演示
      link: https://reserendipity.github.io/SeedVR2-lite/
    - theme: alt
      text: GitHub
      link: https://github.com/ReSerendipity/SeedVR2-lite

features:
  - icon: ⚡
    title: 单步扩散修复
    details: 基于扩散模型单步推理，高效完成视频与图像的超分辨率修复，无需多步迭代。
  - icon: 🖥
    title: 独立运行
    details: 脱离 ComfyUI，通过 FastAPI + Jinja2 提供完整 Web UI，开箱即用。
  - icon: 🧠
    title: 多模型多精度
    details: 支持 3B / 7B / 7B-Sharp 三种模型，含 FP16 全精度与 FP8 量化。
  - icon: 💾
    title: GPU BlockSwap
    details: GPU/CPU 动态换入换出 Transformer 块，大幅降低显存需求（3B-FP8 最低 8GB）。
  - icon: 📦
    title: 批量与断点续跑
    details: 文件夹批量扫描修复 + checkpoint 断点续跑，崩溃后可恢复。
  - icon: 🌍
    title: 五种语言
    details: 内置中文、繁体中文、英文、日文、法文五种语言界面。
---
