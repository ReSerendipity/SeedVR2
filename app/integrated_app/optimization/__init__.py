"""
Optimization module for SeedVR2

Provides memory management, BlockSwap, and various competitive analysis-inspired
optimization modules for running large models on limited VRAM systems.

Modules:
- blockswap: Dynamic block swapping between GPU and CPU (ComfyUI-inspired)
- memory_manager: VRAM/RAM monitoring and model device management
- cache_manager: CPU tensor cache for VRAM pressure relief (RVRT-inspired)
- tile_blend: Spatial and temporal tile blending utilities

Competitive analysis modules (from repo/ 40 repositories):
- vram_monitor: VRAM peak monitoring (DiffBIR-inspired, P1)
- vae_tiled_enhance: VAE tiled processing enhancements (SCST/VEnhancer/DiffBIR, P0-P1)
- temporal_processing: Frame consistency and temporal processing (StableVSR/FlashVSR/Turtle, P0-P2)
- engine_scheduler: Multi-engine scheduling framework (Waifu2x-Extension-GUI, P0-P2)
- diffusion_sampling: Diffusion scheduling, CFG, and samplers (Vivid-VR/Stream-DiffVSR, P0-P2)
- post_processing: Post-processing and color correction (DiffBIR/Real-ESRGAN, P1-P2)
- dit_optimization: DiT model architecture optimizations (FlashVSR/HunyuanVideo, P0-P3)
- video_processing_enhance: Video processing and frame interpolation (VEnhancer/DAIN, P1-P3)
- gpu_compatibility: GPU/hardware compatibility (Anime4KCPP/Waifu2x-Extension-GUI, P1-P3)
- webui_enhancement: WebUI/user interaction (SUPIR/Waifu2x-Extension-GUI, P1-P2)
- vram_toolchain: VRAM optimization toolchain (CogVideo/FlashVSR, P1-P2)
- framework_engineering: Framework and engineering patterns (BasicSR/DiffBIR, P2-P3)
- specialized_engines: Specialized engine/scenario extensions (CodeFormer/Anime4KCPP, P1-P3)
- license_compliance: License compliance reference (Chapter 13-14)
- roadmap: Implementation roadmap (Chapter 15)
"""

# Core modules (always available)
from .gpu.blockswap import apply_block_swap_to_dit, is_blockswap_enabled
from .gpu.memory_manager import clear_memory, get_ram_usage, get_vram_usage

__all__ = [
    # Core
    "apply_block_swap_to_dit",
    "is_blockswap_enabled",
    "clear_memory",
    "get_vram_usage",
    "get_ram_usage",
]

# Competitive analysis modules (lazy import to avoid dependency issues)
__all__.extend(
    [
        "vram_monitor",
        "vae_tiled_enhance",
        "temporal_processing",
        "engine_scheduler",
        "diffusion_sampling",
        "post_processing",
        "dit_optimization",
        "video_processing_enhance",
        "gpu_compatibility",
        "webui_enhancement",
        "vram_toolchain",
        "framework_engineering",
        "specialized_engines",
        "license_compliance",
        "roadmap",
    ]
)


def __getattr__(name):
    """Lazy import for competitive analysis modules"""
    _lazy_modules = {
        "vram_monitor": "app.integrated_app.optimization.gpu.vram_monitor",
        "vae_tiled_enhance": "app.integrated_app.optimization.inference.vae_tiled_enhance",
        "temporal_processing": "app.integrated_app.optimization.inference.temporal_processing",
        "engine_scheduler": "app.integrated_app.optimization.engine.engine_scheduler",
        "diffusion_sampling": "app.integrated_app.optimization.inference.diffusion_sampling",
        "post_processing": "app.integrated_app.optimization.inference.post_processing",
        "dit_optimization": "app.integrated_app.optimization.inference.dit_optimization",
        "video_processing_enhance": "app.integrated_app.optimization.video.video_processing_enhance",
        "gpu_compatibility": "app.integrated_app.optimization.gpu.gpu_compatibility",
        "webui_enhancement": "app.integrated_app.optimization.webui_enhancement",
        "vram_toolchain": "app.integrated_app.optimization.gpu.vram_toolchain",
        "framework_engineering": "app.integrated_app.optimization.engine.framework_engineering",
        "specialized_engines": "app.integrated_app.optimization.engine.specialized_engines",
        "license_compliance": "app.integrated_app.optimization.license_compliance",
        "roadmap": "app.integrated_app.optimization.roadmap",
    }

    if name in _lazy_modules:
        import importlib

        module = importlib.import_module(_lazy_modules[name])
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
