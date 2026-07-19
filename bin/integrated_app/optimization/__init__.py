"""
Optimization module for SeedVR2

Provides memory management and BlockSwap functionality for running
large models on limited VRAM systems (e.g., RTX 5070 Ti 12GB).
"""

from .blockswap import apply_block_swap_to_dit, is_blockswap_enabled
from .memory_manager import clear_memory, get_ram_usage, get_vram_usage

__all__ = [
    "apply_block_swap_to_dit",
    "is_blockswap_enabled",
    "clear_memory",
    "get_vram_usage",
    "get_ram_usage",
]
