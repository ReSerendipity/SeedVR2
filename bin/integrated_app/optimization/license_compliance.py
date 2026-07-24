"""许可证合规速查与警告参考

第十三章：许可证合规速查 - 整合竞品仓库的许可证合规信息
第十四章：各报告共性警告 - 整合需要注意的技术和法律风险

此文件为代码级别的合规参考，供开发者在借鉴竞品代码时自查。

数据来源: readme.txt 第十三、十四章 (40个竞品仓库分析)

---

## 一、可直接借鉴代码的仓库 (BSD/Apache/MIT)

以下仓库的代码可以直接参考和借鉴（需保留原始许可证声明）:

- Real-ESRGAN (BSD-3-Clause)
- BasicSR (Apache-2.0)
- BasicVSR_PlusPlus (BSD-3-Clause)
- Fast-SRGAN (MIT)
- SUPIR (Apache-2.0)
- Upscale-A-Video (BSD-3-Clause)
- CogVideo (Apache-2.0)
- VEnhancer (MIT)
- Vivid-VR (Apache-2.0)
- STAR (Apache-2.0)
- Stream-DiffVSR (Apache-2.0)
- CodeFormer (BSD-3-Clause)
- DeOldify (Apache-2.0)
- RVRT (Apache-2.0)
- Turtle (MIT)
- DiffVSR (Apache-2.0)
- FTVSR (BSD-3-Clause)
- FlashVSR / FlashVSR-v2 (MIT)
- MIA-VSR (Apache-2.0)
- ProPainter (MIT)
- StableVSR (Apache-2.0)
- EvTexture (Apache-2.0)
- DAIN (Apache-2.0)
- SCST (Apache-2.0)
- PaddleGAN (Apache-2.0)
- bilibili-ailab/Real-CUGAN (MIT)
- Anime4KCPP (MIT)
- waifu2x (BSD-2-Clause)
- DiffBIR (Apache-2.0)

## 二、不可直接复制代码的仓库 (GPL/AGPL)

以下仓库仅可参考设计模式和设计思路，不可直接引用代码:
- clarity-upscaler (AGPL-3.0): copyleft 传染性，不可直接引用代码
- Waifu2x-Extension-GUI (AGPL v3): copyleft 传染性，仅参考设计模式
- upscayl (GPL-3.0): 不可复制代码，仅借鉴设计思路

## 三、需审查具体条款的仓库

- HunyuanVideo (Tencent Hunyuan License): 需审查是否允许商业集成
- ComfyUI-SeedVR2 (自定义开源): 官方仓库，分析仅作参考
- SeedVR2-3B (自定义开源): 官方仓库，分析仅作参考

## 四、共性技术警告

1. **DAIN 自定义 CUDA 扩展已过时**: 旧版 PyTorch 1.0 依赖，不建议直接集成，
   现代有 xformers/Triton 等替代方案。

2. **waifu2x 基于 Torch7 (Lua)**: 技术栈过时，模型需转换后才能复用。

3. **RCOD-SR 代码尚未发布**: 只能基于论文分析，无法实际借鉴代码。

4. **EvTexture 依赖事件相机数据**: 与 SeedVR2 通用场景不兼容。

5. **HunyuanVideo Tencent Hunyuan License**: 需审查是否允许商业集成。

6. **VEnhancer 依赖 fairscale**: 梯度检查点可能与 SeedVR2 的 PyTorch 版本冲突。

7. **不要照搬 DAIN 的旧版 CUDA 编译方式**: 现代 PyTorch + xformers/Triton
   是更好的替代方案。

---

开发者在实现竞品建议时，请遵循以下规则:

1. 从 GPL/AGPL 仓库借鉴时，只参考设计模式，不复制代码
2. 借鉴 BSD/Apache/MIT 仓库代码时，在文件头添加原始许可证声明
3. 使用 HunyuanVideo 技术前，审查其许可证是否兼容项目用途
4. 避免引入已过时的技术栈 (Torch7/Lua, 旧版 CUDA 扩展)
5. 对依赖冲突 (如 fairscale 版本) 提前检测并处理
"""

# 此文件为纯文档参考，不包含可执行代码
# 开发者应在实际编码时参考此文件的合规信息
