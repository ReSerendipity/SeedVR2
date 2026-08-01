# 配置与部署优化审查

> **审查时间**: 2026-08-01
> **审查范围**: config.yaml, configs_3b/config.json, configs_7b/config.json, requirements*.txt, 启动脚本

---

## 1. config.yaml 审查

### 1.1 一致性检查

| 配置项 | 当前值 | 代码默认值 | 状态 |
|---|---|---|---|
| `model.default_size` | `3b` | `3b` | ✅ 一致 |
| `model.default_precision` | `auto` | 代码中自动检测 | ✅ 一致 |
| `inference.inference_mode` | `distilled` | `distilled` | ✅ 一致 |
| `inference.color_correction` | `wavelet` | `lab` (ImageInferenceConfig) | ⚠️ 配置覆盖代码默认 |
| `inference.swap_io_components` | `true` | `true` | ✅ 一致 |
| `inference.attention_mode` | `sdpa` | `sdpa` | ✅ 一致 |
| `restore.default_resolution_h` | `1080` | `1080` | ✅ 一致 |
| `restore.default_resolution_w` | `1920` | `1920` | ✅ 一致 |
| `server.host` | `127.0.0.1` | `127.0.0.1` | ✅ 一致 |
| `server.port` | `7870` | `7870` | ✅ 一致 |
| `i18n.default_locale` | `zh` | `zh` | ✅ 一致 |

### 1.2 发现的问题

**无严重问题。** 以下为注意事项：

1. `color_correction: wavelet` 与 `ImageInferenceConfig` 的默认值 `lab` 不一致 — 但这是配置覆盖代码默认值的正常行为，用户可以自行修改。如果希望统一，可在 `ImageInferenceConfig.from_config_dict` 中读取此值。
2. `blocks_to_swap: 32` — 对 3B 模型（32 层）是合理的，交换所有块。但对 7B（36 层）应为 36 — 但 7B 配置文件 `configs_7b/config.json` 中的 `blocks_to_swap: 0` 会覆盖此值。
3. `model.auto_load: true` — 启动时自动加载模型配置。注意这不加载大模型权重（延迟加载策略）。

### 1.3 建议改进

1. `inference.color_correction` 默认值建议统一为 `lab`（与 ImageInferenceConfig 一致），或更新代码默认值
2. `user_preferences.blocks_to_swap: 0` 与 `inference.blocks_to_swap: 32` 不一致 — 前者用于 WebUI 用户偏好，后者用于引擎配置，不需要统一但需文档说明

---

## 2. 模型配置一致性 (configs_3b vs configs_7b)

### 2.1 架构参数对比

| 参数 | 3B | 7B | CONSTRAINTS.md 要求 | 状态 |
|---|---|---|---|---|
| `dit.vid_dim` | 2560 | 3072 | 3B=2560, 7B=3072 | ✅ |
| `dit.num_layers` | 32 | 36 | 3B=32, 7B=36 | ✅ |
| `dit.mlp_type` | swiglu | normal | 3B=swiglu, 7B=normal | ✅ |
| `dit.heads` | 20 | 24 | — | ✅ |
| `dit.head_dim` | 128 | 128 | — | ✅ |
| `dit.patch_size` | [1,2,2] | [1,2,2] | — | ✅ |
| `dit.window` | [4,3,3] | [4,3,3] | — | ✅ |
| `dit.blocks_to_swap` | 32 | 0 | — | ✅ (7B 不用 BlockSwap) |
| `dit.swap_io_components` | true | true | — | ⚠️ 注意：CONSTRAINTS.md 警告此值为 true 可能导致内存溢出 |

### 2.2 扩散参数对比

| 参数 | 3B | 7B | 状态 |
|---|---|---|---|
| `diffusion.schedule.type` | lerp | lerp | ✅ |
| `diffusion.sampler.type` | euler | euler | ✅ |
| `diffusion.timesteps.sampling.steps` | 50 | 50 | ✅ |
| `diffusion.cfg.scale` | 7.5 | 7.5 | ✅ |
| `diffusion.timesteps.transform` | true | true | ✅ |

### 2.3 VAE 参数对比

完全一致，使用同一个 VAE checkpoint 和配置。✅

### 2.4 注意事项

- `swap_io_components: true` 在 CONSTRAINTS.md 中有警告：可能导致内存溢出（将 I/O 组件卸载到 CPU RAM）。这是一个已知的权衡，当前保持不变。
- `window_method` 列表长度与 `num_layers` 不匹配 — 3B 有 2 个方法但 32 层，代码会自动扩展。✅ 符合 CONSTRAINTS.md 要求。

---

## 3. 依赖一致性审查

### 3.1 requirements.txt vs requirements-lock.txt

`requirements.txt` 是锁定版本（exact version），与 `requirements-lock.txt` 内容相同。`requirements-dev.txt` 包含开发工具。

### 3.2 发现的问题

1. **`pytest-cov` 缺失于 `requirements-dev.txt`** — 已修复，添加了 `pytest-cov>=5.0`
2. **`requirements-lock.txt` 无 `pytest-cov`** — 锁定文件不含开发依赖，这是正确的

### 3.3 版本检查

| 关键依赖 | 版本 | 状态 |
|---|---|---|
| `torch` | 2.11.0+cu128 | ✅ CUDA 12.8 |
| `fastapi` | 0.137.0 | ✅ |
| `starlette` | 1.3.1 | ⚠️ CONSTRAINTS.md 提到 1.0.0 有兼容问题，但 1.3.1 应已修复 |
| `pydantic` | 2.13.4 | ✅ |
| `uvicorn` | 0.49.0 | ✅ |
| `omegaconf` | 2.3.1 | ✅ |
| `safetensors` | 0.8.0 | ✅ |
| `einops` | 0.8.2 | ✅ |

---

## 4. 启动脚本审查

### 4.1 start.bat

- ✅ 使用纯 ASCII 英文
- ✅ 自动检测 WinPython 路径（WPy64-312101 优先，然后通配符搜索）
- ✅ 设置 `KMP_DUPLICATE_LIB_OK=TRUE` 环境变量
- ✅ 错误处理：未找到 WinPython 时显示友好提示
- ✅ 使用 `cd /d "%~dp0"` 切换到脚本目录

### 4.2 run_verify.bat

- ✅ 运行 `verify_engine.py`（配置/GPU/引擎导入三项自检，不加载模型）
- ✅ 使用纯 ASCII 英文

### 4.3 run_checks.bat

- ✅ 一键质量门禁（ruff → black → mypy → pytest）
- ✅ 支持 `--fast` 标志跳过 mypy/pytest
- ✅ 使用纯 ASCII 英文
- ✅ 正确报告失败步骤

---

## 5. .gitignore 审查

- ✅ WinPython 环境被排除
- ✅ 缓存目录被排除（.pytest_cache, .ruff_cache, .mypy_cache）
- ✅ 覆盖率报告被排除
- ✅ 日志目录被排除
- ✅ 运行产物（dogfood-output）被排除

---

## 6. 总结

### 已修复

1. ✅ `requirements-dev.txt` 添加 `pytest-cov>=5.0`

### 无需修改

1. config.yaml 配置一致性检查通过
2. 模型配置 (configs_3b/7b) 与 CONSTRAINTS.md 对齐
3. 启动脚本符合规范（纯 ASCII、自动检测、错误处理）
4. 依赖版本合理

### 建议关注

1. `swap_io_components: true` — 已知可能导致内存溢出的权衡配置
2. `color_correction` 默认值在 config 和代码间不一致（非 bug，配置覆盖行为）
3. `starlette 1.3.1` — CONSTRAINTS.md 提到 1.0.0 兼容问题，但 1.3.1 应已修复

---

*本报告为配置与部署优化的审查结果。除 `requirements-dev.txt` 添加 `pytest-cov` 外，未修改其他配置文件。*
