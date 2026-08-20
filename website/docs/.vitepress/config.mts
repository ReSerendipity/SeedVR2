import { defineConfig } from 'vitepress'

export default defineConfig({
  // 部署在 GitHub Pages 的 /docs/ 子路径（与根路径的 demo 演示站并存）
  base: '/SeedVR2-lite/docs/',
  lang: 'zh-CN',
  title: 'SeedVR2-lite',
  description: '基于 SeedVR2 扩散模型的视频与图像超分辨率修复工具箱 — 独立运行、开箱即用',
  head: [
    ['meta', { name: 'theme-color', content: '#5e7d5a' }],
  ],
  themeConfig: {
    logo: '/SeedVR2-lite/docs/logo.svg',
    nav: [
      { text: '首页', link: '/' },
      { text: '快速开始', link: '/guide/quickstart' },
      { text: '模型下载', link: '/guide/models' },
      { text: '工作流', link: '/guide/workflow' },
      { text: '在线演示', link: 'https://reserendipity.github.io/SeedVR2-lite/' },
      { text: 'GitHub', link: 'https://github.com/ReSerendipity/SeedVR2-lite' },
    ],
    sidebar: [
      {
        text: '入门',
        items: [
          { text: '项目简介', link: '/' },
          { text: '快速开始（5 分钟）', link: '/guide/quickstart' },
          { text: '安装与运行', link: '/guide/install' },
          { text: '模型下载与选型', link: '/guide/models' },
        ],
      },
      {
        text: '使用指南',
        items: [
          { text: '界面与功能', link: '/guide/usage' },
          { text: '工作流与 ComfyUI 对比', link: '/guide/workflow' },
          { text: '显存优化与 BlockSwap', link: '/guide/vram' },
          { text: '常见问题（FAQ）', link: '/guide/faq' },
        ],
      },
      {
        text: '进阶',
        items: [
          { text: '技术架构', link: '/guide/architecture' },
          { text: 'API 参考', link: '/guide/api' },
          { text: '安全与合规', link: '/guide/security' },
        ],
      },
    ],
    footer: {
      message: 'Apache-2.0 License · Copyright 2024-2026 ReSerendipity · 独立第三方工具，与字节跳动及其 Seed 团队无隶属关系',
      copyright: '基于 SeedVR2（ByteDance Seed 团队 & 南洋理工大学 S-Lab 联合开源）构建',
    },
    search: {
      provider: 'local',
    },
  },
})
