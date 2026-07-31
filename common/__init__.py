# // Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# //
# // Licensed under the Apache License, Version 2.0 (the "License");
# // you may not use this file except in compliance with the License.
# // You may obtain a copy of the License at
# //
# //     http://www.apache.org/licenses/LICENSE-2.0
# //
# // Unless required by applicable law or agreed to in writing, software
# // distributed under the License is distributed on an "AS IS" BASIS,
# // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# // See the License for the specific language governing permissions and
# // limitations under the License.

"""Common utilities package for SeedVR2 video restoration model.

This package provides shared utilities used across the project, including:
- Configuration loading and management with OmegaConf
- Caching mechanisms for reusable computation results
- Decorators for distributed training, logging, and threading
- Logging utilities with rank-aware formatting
- List partitioning and manipulation utilities
- Random seed management for reproducibility
- Diffusion model components (schedules, samplers, timesteps)
- Distributed training utilities (DDP, sequence parallel, FSDP)

Modules:
    config: Configuration loading and object instantiation from config files
    utils: PyTorch tensor operation utilities (safe padding, interpolation)
    cache: Key-value caching for expensive computation results
    decorators: Function decorators for distributed execution, logging, timing
    logger: Logging setup with distributed rank information
    partition: List partitioning and rotation utilities
    seed: Random seed initialization for reproducibility
    diffusion: Diffusion model sampling infrastructure
    distributed: Distributed training and parallelism utilities
"""
