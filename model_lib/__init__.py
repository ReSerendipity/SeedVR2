# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SeedVR2 模型实现包。

此 __init__.py 将项目根的 `model_lib/` 声明为常规包（regular package），
避免与 `app/models/`（含 __init__.py 的常规包）在 sys.path 上发生同名遮蔽，
确保 `import model_lib.video_vae_v3` / `model_lib.dit` / `model_lib.dit_v2` 始终解析到本项目模型目录。

子包：
- dit / dit_v2: Diffusion Transformer 主干
- video_vae_v3: 视频因果 VAE
"""
