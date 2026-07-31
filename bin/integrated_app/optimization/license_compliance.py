"""许可证合规速查与技术警告参考模块

所属项目: SeedVR2 (SeedVR2 视频/图像修复应用)
核心技术栈: 开源许可证合规, 法律风险参考, 技术债务管理

本模块为纯文档参考文件，整合40个竞品仓库的许可证合规信息和共性技术警告，
供开发者在借鉴竞品代码设计时进行自查，避免许可证冲突和引入过时技术。

模块包含:
- 可直接借鉴代码的仓库列表 (BSD/Apache/MIT 宽松许可证)
- 不可直接复制代码的仓库列表 (GPL/AGPL copyleft 传染性许可证)
- 需审查具体条款的仓库 (自定义许可证)
- 共性技术警告: 过时依赖、技术栈兼容性、版本冲突风险

数据来源: readme.txt 第十三、十四章 (40个竞品仓库分析报告)

开发者合规规则:
1. 从 GPL/AGPL 仓库借鉴时，只参考设计模式，不复制代码
2. 借鉴 BSD/Apache/MIT 仓库代码时，在文件头添加原始许可证声明
3. 使用 HunyuanVideo 等自定义许可证技术前，审查其许可证是否兼容商业用途
4. 避免引入已过时的技术栈 (Torch7/Lua, 旧版 CUDA 扩展)
5. 对依赖冲突 (如 fairscale 版本) 提前检测并处理
"""

# ===========================================================================
# 一、可直接借鉴代码的仓库 (BSD/Apache/MIT)
# ===========================================================================
# 以下仓库的代码可以直接参考和借鉴（需保留原始许可证声明）:
#
# BSD-3-Clause:
# - Real-ESRGAN, BasicVSR_PlusPlus, Upscale-A-Video, CodeFormer, FTVSR
#
# Apache-2.0:
# - BasicSR, SUPIR, CogVideo, Vivid-VR, STAR, Stream-DiffVSR, DeOldify,
#   RVRT, DiffVSR, MIA-VSR, StableVSR, EvTexture, DAIN, SCST, PaddleGAN,
#   DiffBIR
#
# MIT:
# - Fast-SRGAN, VEnhancer, Turtle, FlashVSR/FlashVSR-v2, ProPainter,
#   bilibili-ailab/Real-CUGAN, Anime4KCPP
#
# BSD-2-Clause:
# - waifu2x

PERMISSIVE_LICENSED_REPOS: dict[str, str] = {
    "Real-ESRGAN": "BSD-3-Clause",
    "BasicSR": "Apache-2.0",
    "BasicVSR_PlusPlus": "BSD-3-Clause",
    "Fast-SRGAN": "MIT",
    "SUPIR": "Apache-2.0",
    "Upscale-A-Video": "BSD-3-Clause",
    "CogVideo": "Apache-2.0",
    "VEnhancer": "MIT",
    "Vivid-VR": "Apache-2.0",
    "STAR": "Apache-2.0",
    "Stream-DiffVSR": "Apache-2.0",
    "CodeFormer": "BSD-3-Clause",
    "DeOldify": "Apache-2.0",
    "RVRT": "Apache-2.0",
    "Turtle": "MIT",
    "DiffVSR": "Apache-2.0",
    "FTVSR": "BSD-3-Clause",
    "FlashVSR": "MIT",
    "FlashVSR-v2": "MIT",
    "MIA-VSR": "Apache-2.0",
    "ProPainter": "MIT",
    "StableVSR": "Apache-2.0",
    "EvTexture": "Apache-2.0",
    "DAIN": "Apache-2.0",
    "SCST": "Apache-2.0",
    "PaddleGAN": "Apache-2.0",
    "Real-CUGAN": "MIT",
    "Anime4KCPP": "MIT",
    "waifu2x": "BSD-2-Clause",
    "DiffBIR": "Apache-2.0",
}

# ===========================================================================
# 二、不可直接复制代码的仓库 (GPL/AGPL)
# ===========================================================================
# 以下仓库仅可参考设计模式和设计思路，不可直接引用代码 (copyleft 传染性):
# - clarity-upscaler (AGPL-3.0)
# - Waifu2x-Extension-GUI (AGPL v3)
# - upscayl (GPL-3.0)

COPYLEFT_LICENSED_REPOS: dict[str, str] = {
    "clarity-upscaler": "AGPL-3.0",
    "Waifu2x-Extension-GUI": "AGPL-3.0",
    "upscayl": "GPL-3.0",
}

# ===========================================================================
# 三、需审查具体条款的仓库
# ===========================================================================
# - HunyuanVideo (Tencent Hunyuan License): 需审查是否允许商业集成
# - ComfyUI-SeedVR2 (自定义开源): 官方仓库，分析仅作参考
# - SeedVR2-3B (自定义开源): 官方仓库，分析仅作参考

CUSTOM_LICENSE_REPOS: dict[str, str] = {
    "HunyuanVideo": "Tencent Hunyuan License",
    "ComfyUI-SeedVR2": "自定义开源",
    "SeedVR2-3B": "自定义开源",
}

# ===========================================================================
# 四、共性技术警告
# ===========================================================================

TECHNICAL_WARNINGS: list[dict[str, str]] = [
    {
        "id": "DAIN_CUDA_OUTDATED",
        "severity": "high",
        "repository": "DAIN",
        "description": "DAIN 自定义 CUDA 扩展已过时，依赖旧版 PyTorch 1.0",
        "recommendation": "不建议直接集成，使用 xformers/Triton 等现代替代方案",
    },
    {
        "id": "WAIFU2X_TORCH7",
        "severity": "medium",
        "repository": "waifu2x",
        "description": "waifu2x 基于 Torch7 (Lua) 技术栈，已过时",
        "recommendation": "模型需转换后才能复用，不推荐直接使用原始代码",
    },
    {
        "id": "RCOD_SR_UNPUBLISHED",
        "severity": "info",
        "repository": "RCOD-SR",
        "description": "RCOD-SR 代码尚未发布",
        "recommendation": "只能基于论文分析，无法实际借鉴代码",
    },
    {
        "id": "EVTEXTURE_EVENT_CAMERA",
        "severity": "medium",
        "repository": "EvTexture",
        "description": "EvTexture 依赖事件相机数据",
        "recommendation": "与 SeedVR2 通用图像/视频修复场景不兼容",
    },
    {
        "id": "HUNYUANVIDEO_LICENSE",
        "severity": "high",
        "repository": "HunyuanVideo",
        "description": "HunyuanVideo 使用 Tencent Hunyuan License",
        "recommendation": "使用前审查许可证是否允许商业集成",
    },
    {
        "id": "VENHANCER_FAIRSCALE",
        "severity": "medium",
        "repository": "VEnhancer",
        "description": "VEnhancer 依赖 fairscale 梯度检查点",
        "recommendation": "可能与 SeedVR2 的 PyTorch 版本产生冲突，需提前检测",
    },
    {
        "id": "OLD_CUDA_COMPILATION",
        "severity": "high",
        "repository": "DAIN",
        "description": "旧版 CUDA 扩展编译方式已过时",
        "recommendation": "使用现代 PyTorch + xformers/Triton 替代",
    },
]


def get_permissive_repos() -> dict[str, str]:
    """获取可直接借鉴的宽松许可证仓库列表。

    Returns:
        {仓库名: 许可证类型} 字典
    """
    return dict(PERMISSIVE_LICENSED_REPOS)


def get_copyleft_repos() -> dict[str, str]:
    """获取不可直接复制代码的 copyleft 许可证仓库列表。

    Returns:
        {仓库名: 许可证类型} 字典
    """
    return dict(COPYLEFT_LICENSED_REPOS)


def get_technical_warnings() -> list[dict[str, str]]:
    """获取共性技术警告列表。

    Returns:
        技术警告字典列表，每项包含 id, severity, repository, description, recommendation
    """
    return list(TECHNICAL_WARNINGS)


def is_code_safe_to_reference(repo_name: str) -> tuple[bool, str]:
    """检查指定仓库的代码是否可以安全参考/复制。

    Args:
        repo_name: 仓库名称

    Returns:
        (是否安全, 说明信息) 元组
    """
    if repo_name in PERMISSIVE_LICENSED_REPOS:
        return True, f"许可证 {PERMISSIVE_LICENSED_REPOS[repo_name]}，可直接参考（需保留许可证声明）"
    if repo_name in COPYLEFT_LICENSED_REPOS:
        return False, f"许可证 {COPYLEFT_LICENSED_REPOS[repo_name]}，仅可参考设计模式，不可复制代码"
    if repo_name in CUSTOM_LICENSE_REPOS:
        return False, f"许可证 {CUSTOM_LICENSE_REPOS[repo_name]}，需先审查许可证条款"
    return False, "未知仓库，建议先审查其许可证"
