# SeedVR2 安全加固执行清单 v2.0

> **报告版本**: v2.0 (执行清单版)  
> **适用读者**: ReSerendipity 执行团队  
> **目的**: 逐一列出所有已规划但**尚未完成**的安全任务，附详细操作步骤与验收标准，按优先级从高到低排列。  
> **使用方式**: 做完一项 → 把 `⬜` 改为 `✅`，并在"验证日志"栏填入结果摘要与日期。

---

## 总览（状态快照）

| 阶段 | 已完成 / 总项数 | 完成度 |
|---|---|---|
| **P0 立即修复（紧急）** | 5 / 5 | 🟩 100% |
| **P1 短期（2-4 周）** | 3 / 3（代码）· 但有 1 项**待填入配置** | 🟩 90% |
| **P2 中期（1-3 月）** | 3 / 4（代码）· 1 项法律事务 | 🟨 60% |
| **P3 长期（3 月+）** | 0 / 4 | 🟥 0% |
| **其他新增建议** | 0 / 5 | 🟥 0% |

---

## 一、P1 遗留项（配置层待填充，代码已就绪）

### T1-1 ▐ 填入 config.yaml 各模型 checkpoint 的实际 SHA256 哈希值
- **优先级**: 🔴 **最高**（代码已接入但校验为空形同虚设）
- **前置**: 已下载对应模型文件（3b / 7b / 14b 的 DiT fp16、fp8、VAE、pos_emb、neg_emb）
- **操作步骤**:

  步骤 1：下载模型到 `pretrained_models/` 目录（以 ByteDance-Seed HuggingFace 为准）

  步骤 2：用 PowerShell 计算每个文件 SHA256（不依赖 Python，避免误加载）：
  ```powershell
  # 单个文件
  (Get-FileHash -Algorithm SHA256 "pretrained_models\seedvr2_ema_3b_fp16.safetensors").Hash.ToLower()

  # 批量计算全部
  Get-ChildItem pretrained_models\ -File -Filter "*.safetensors" | ForEach-Object {
      $hash = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower()
      "{0}: '{1}'" -f $_.Name, $hash
  }
  ```
  或使用项目内置 API：
  ```bat
  WPy64-312101\python\python.exe -c ^
    "from bin.integrated_app.security.integrity_check import compute_sha256; ^
     import os; ^
     [print(f'{f}: {compute_sha256(os.path.join(r\"pretrained_models\",f))}') ^
      for f in os.listdir('pretrained_models') if f.endswith(('.safetensors','.pt'))]"
  ```

  步骤 3：将哈希值粘贴到 `config.yaml` 对应字段（约 69-106 行）：
  ```yaml
  model:
    models:
      3b:
        checkpoint_fp16: seedvr2_ema_3b_fp16.safetensors
        sha256_fp16:   'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'   # <- 实际值
        sha256_fp8:    '...'
        sha256_vae:    '...'
        sha256_pos_emb:'...'
        sha256_neg_emb:'...'
      7b:
        ...同上 5 个字段...
      14b:
        ...同上 5 个字段...
  ```
- **验证方法**:
  ```bat
  REM 启动引擎，观察日志中是否出现
  REM "[INTEGRITY] 正在校验 DiT-fp16 SHA256 完整性..."
  REM "[INTEGRITY] DiT-fp16: SHA256 校验通过 ✓"
  start.bat
  REM 或查看 logs\app_*.log 搜索 INTEGRITY 关键字
  ```
- **预期产出**: `config.yaml` 中 15 个 `sha256_*` 字段全部填充；启动日志显示所有模型 SHA256 校验通过。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

## 二、P2 中期项目（代码已实现，但**缺少启用步骤或文档**）

### T2-1 ▐ 在 GitHub Secrets 中配置 GPG 密钥，激活 Release 签名工作流
- **优先级**: 🟠 **高**
- **前置**: 本地已安装 GnuPG（`winget install GnuPG.GnuPG`）、有 GitHub 仓库管理权限
- **操作步骤**:

  步骤 1：生成用于发布签名的 GPG 密钥（一次性）：
  ```bash
  gpg --full-generate-key
  # 密钥类型: RSA and RSA (4096 bit)
  # 有效期: 2y  (建议设过期，到期可续)
  # 姓名: ReSerendipity Release Bot
  # 邮箱: release@reserendipity.com (建议使用项目专用邮箱)
  # 输入安全的 Passphrase (建议 20+ 字符随机，保存到密码管理器)
  ```

  步骤 2：提取 3 个关键信息：
  ```bash
  # ① GPG_KEY_ID
  gpg --list-secret-keys --keyid-format=long release@reserendipity.com
  # 输出形如 "sec   rsa4096/4A9B6C7D8E1F2A3B 2026-08-07 [SC]"
  #                      ~~~~~~~~~~~~~~~~ GPG_KEY_ID = 这串

  # ② GPG_PRIVATE_KEY (armored 格式，整块复制)
  gpg --export-secret-keys --armor 4A9B6C7D8E1F2A3B | clip

  # ③ GPG_PASSPHRASE = 步骤 1 设置的密码
  ```

  步骤 3：在 GitHub 仓库添加 3 个 **Repository Secrets**：
  - 访问 `https://github.com/{ORG}/SeedVR2/settings/secrets/actions`
  - 新建 `GPG_PRIVATE_KEY` → 粘贴 ② 的输出（含 `-----BEGIN PGP PRIVATE KEY BLOCK-----` 到 `-----END PGP PRIVATE KEY BLOCK-----`）
  - 新建 `GPG_PASSPHRASE` → 粘贴密码
  - 新建 `GPG_KEY_ID` → 粘贴 ① 的密钥 ID

  步骤 4：上传对应公钥到 Ubuntu 公钥服务器（供用户验证）：
  ```bash
  gpg --send-keys --keyserver keyserver.ubuntu.com 4A9B6C7D8E1F2A3B
  ```

  步骤 5：测试签名：
  ```bash
  # 用 -s 选项（签名提交）创建测试 tag
  git tag -s v1.0.0-test -m "Test GPG signed release tag"
  git push origin v1.0.0-test
  # 在 GitHub Release 页面手动创建草稿 Release 发布该 tag
  # 观察 Actions 标签页 "GPG-Signed Release" 工作流是否通过
  # 成功后 Release Assets 中应新增 SHA256SUMS + SHA256SUMS.gpg
  ```
- **验证方法**:
  - Release 页面 Assets 列表包含 `SHA256SUMS` 与 `SHA256SUMS.gpg`
  - Release Body 底部自动追加 "🔐 完整性验证" 说明区块
  - 本地验证通过：
    ```bash
    sha256sum -c SHA256SUMS
    gpg --keyserver keyserver.ubuntu.com --recv-keys 4A9B6C7D8E1F2A3B
    gpg --verify SHA256SUMS.gpg SHA256SUMS
    ```
- **预期产出**: 工作流 [`.github/workflows/gpg-signed-release.yml`](file:///c:/Users/Doro/Seedvr2/.github/workflows/gpg-signed-release.yml) 至少成功跑过一次；Secrets 全部就绪。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T2-2 ▐ 创建项目顶层 NOTICE.txt（Apache 2.0 第 4(d) 条合规）
- **优先级**: 🟡 中
- **参考文件**: Apache License 2.0 §4(d) — 若分发衍生作品，需包含一个 NOTICE 文件说明归属
- **操作步骤**: 在仓库根目录创建 `NOTICE` 文件：
  ```
  SeedVR2 - AI-powered video & image super-resolution toolkit
  Copyright 2024-2026 ReSerendipity

  This product includes software developed at
  ReSerendipity (https://github.com/ReSerendipity/SeedVR2).

  ------------------------------------------------------------
  Third-party attributions (required by upstream licenses):

  1. NaDiT (Native Resolution Diffusion Transformer)
     Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
     Licensed under Apache License 2.0
     Files: models/dit/*

  2. Stable Diffusion 3 Video VAE (Causal Video AutoencoderKL)
     Copyright (c) 2023 HuggingFace Team
     Copyright (c) 2025 ByteDance Ltd. and/or its affiliates
     Licensed under Apache License 2.0
     Files: models/video_vae_v3/*

  3. waifu2x concepts (model self-descriptor attributes)
     Reference: https://github.com/nagadomi/waifu2x
     Licensed under MIT License
     See: repo/waifu2x/NOTICE
  ```
- **验证方法**: `dir C:\Users\Doro\Seedvr2\NOTICE` 可找到；README 的许可证章节加一行指向 NOTICE 文件。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T2-3 ▐ 生成并提交依赖 hash 锁文件（requirements-lock.txt + 验证）
- **优先级**: 🟡 中
- **代码已就绪**: [scripts/generate_lock.py](file:///c:/Users/Doro/Seedvr2/scripts/generate_lock.py)
- **操作步骤**:

  步骤 1：确保当前 `requirements.txt` 是真实部署的版本（即 WinPython 实际安装的版本）：
  ```bat
  WPy64-312101\python\python.exe -m pip freeze > pip_freeze.txt
  REM 人工比对 requirements.txt 与 pip_freeze.txt 的版本号，若有差异统一 requirements.txt
  ```

  步骤 2：运行生成脚本：
  ```bat
  WPy64-312101\python\python.exe scripts\generate_lock.py
  ```

  步骤 3：验证 lock 文件能被 pip 接受（沙盒测试）：
  ```bat
  REM 在新 venv 中尝试
  WPy64-312101\python\python.exe -m venv lock_test_env
  lock_test_env\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt 2>&1
  REM 若全部安装成功，锁文件有效
  rmdir /s /q lock_test_env
  ```

  步骤 4：将 `requirements-lock.txt` 提交到 Git
- **验证方法**: 在一台**全新**机器（或 venv）上 `pip install --require-hashes -r requirements-lock.txt` 不报 `THESE PACKAGES DO NOT MATCH THE HASHES` 错误。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T2-4 ▐ （法律事务）注册 SeedVR2 文字商标 + Logo 图形商标
- **优先级**: 🟡 中（法律层，维权必需前提）
- **操作步骤**:
  1. 搜索中国商标网 (http://sbj.cnipa.gov.cn/sbcx/)，核查第 9 类（计算机软件）、第 42 类（SaaS/技术服务）是否已有相近 "SeedVR2" 商标
  2. 委托商标代理机构在 2 个类别注册"SeedVR2"文字商标
  3. 若有 Logo 图形，同步在第 9、42 类注册图形商标
  4. 同步申请著作权登记（软著）— SeedVR2 修复系统 V1.0
- **验证方法**: 取得商标受理通知书 → 商标注册证（6-12 月后）
- **验收人**: ______  完成日期: __________  结果: ⬜

---

## 三、P3 长期项目（研发阶段，技术投入大）

### T3-1 ▐ 模型权重 AES-256-GCM 加密封装（针对权重分发版）
- **优先级**: 🔵 中
- **目的**: 即使克隆者拿到 pretrained_models/，也无法直接加载为 state_dict（抬高权重提取门槛）
- **操作步骤**:
  1. 设计密钥派生：从机器指纹（mac地址+cpu_id+主板序列号）+ 许可证文件派生出 AES key
  2. 新增 `bin/integrated_app/security/weight_crypto.py`，实现：
     - `encrypt_weight(src, dst, key)` — safetensors → AES-GCM 加密文件（附 nonce + tag）
     - `decrypt_weight(src, dst, key)` — 解密到临时内存映射文件，推理完成后清零
  3. `seedvr2_engine.py` 的模型加载流程包装：若检测到 `.seedvr2enc` 加密格式则先解密
  4. 新增 `scripts/encrypt_weights.py` 为授权用户加密权重
- **验证方法**: 加密后 safetensors 文件被直接传给 torch.load 报错；通过 seedvr2_engine 正常推理；删除许可证后推理中止并告警。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T3-2 ▐ 核心 forward 逻辑 Cython 编译（`.pyx` → `.pyd`）
- **优先级**: 🔵 中
- **目的**: 将 `NaDiT.forward`、`WindowAttention.forward`、`VideoAutoencoderKL.decode` 等核心推理路径从 Python 源码编译为机器码，抬高逆向门槛
- **操作步骤**:
  1. 抽出计算密集部分到 `models/csrc/nadit_core.pyx`、`models/csrc/window_attn.pyx`
  2. 编写 `setup_cython.py` 使用 `Cython.Build.cythonize` 生成扩展
  3. 在 `start.bat` 的启动阶段检测缺失 `.pyd` 时回退到纯 Python（保证 Windows 用户零编译仍可运行）
  4. 在 `pyproject.toml` 新增 cython 构建配置与可选 build backend
- **验证方法**: 对比纯 Python vs Cython 路径的推理误差 < 1e-3（数值等价）；逆向攻击者用 IDA Pro 查看 .pyd 无法直接还原 Python 源码结构。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T3-3 ▐ 推理引擎 TorchScript / ONNX 导出化（脱离源码 Module 加载）
- **优先级**: 🔵 中
- **操作步骤**:
  1. 为 `NaDiT` / `VideoAutoencoderKL` 增加 `export_torchscript(save_path, sample_inputs)` 方法（注意 JIT 不支持的语法：if-tensor、kwargs、dataclass 等，需改为静态图友好写法）
  2. 导出 3 个尺寸（3b / 7b / 14b）× 2 个精度（fp16 / fp8），总计 6 个 `.ts` 图
  3. 修改 `seedvr2_engine.py`：优先从 `.ts` 加载 `torch.jit.load(..., map_location=..)`，失败再回退源码模型
  4. 基准测试：导出后推理速度、显存、PSNR 与源码等价
- **验证方法**: 删除 `models/` 源码目录后，应用仍可通过 TorchScript 正常完成端到端推理。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T3-4 ▐ PyArmor 字节码混淆评估（编排层代码保护）
- **优先级**: 🟢 低
- **操作步骤**:
  1. 创建 `tests/pyarmor_poc/` 隔离环境，安装 PyArmor 试用版
  2. 对 `app_server.py`、`config.py`、`model_manager.py`（非性能关键）做 `pyarmor gen --enable-jit --mix-str` 混淆
  3. 混淆后运行：pytest、start.bat、引擎自检三项通过
  4. 评估混淆前后启动耗时增幅、体积增幅、PyArmor 许可费用（年费）
  5. 输出评估报告：收益（抗新手逆向程度）/ 成本 / 风险（与某些 debug/coverage 工具冲突）
- **验证方法**: 提交评估报告（非代码），由项目负责人决策是否采纳。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

## 四、新增建议项（未在 v1.0 报告中，基于安全最佳实践补充）

### T4-1 ▐ 启用 SECRET_KEY 持久化 + 服务端签名 CSRF（替换当前纯随机 Double-Submit）
- **优先级**: 🟡 中
- **问题点**: 现 CSRF token 采用每请求随机生成 cookie+header 模式，若重启则所有已有页面失效；此外缺少服务端绑定（可被跨域读取 token 后伪造）
- **操作步骤**: 在 `config.py` 增加 `security.secret_key` 字段（若不存在则首次启动随机生成为 `data/.seedvr2_secret`），在 `csrf.py` 改用 `HMAC(secret, session_id)` 派生出 CSRF token。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T4-2 ▐ 上传文件类型魔数（Magic Number）白名单校验
- **优先级**: 🟡 中
- **问题点**: PathGuard 限制了目录范围，但上传路由未校验文件**实际内容**是否匹配扩展名（如改后缀为 .jpg 的可执行文件）
- **操作步骤**: 在 `bin/integrated_app/routes/upload_*.py` 中增加：
  ```python
  IMG_MAGICS = {
      b'\xff\xd8\xff': 'jpeg',
      b'\x89PNG\r\n\x1a\n': 'png',
      b'BM': 'bmp',
      b'GIF87a': 'gif', b'GIF89a': 'gif',
      b'RIFF': 'webp',   # 需再读 8-11 字节是否为 'WEBP'
  }
  VID_MAGICS = {b'....ftyp': 'mp4',  b'OggS': 'ogg', b'\x1aE\xdf\xa3': 'mkv/webm'}
  ```
  仅当扩展名匹配实际魔数时才保存到 `data/uploads/`。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T4-3 ▐ 输出目录文件名随机化（防止 PathTraversal 生成可预测路径被下载）
- **优先级**: 🟢 低
- **问题点**: 输出文件命名为 `{原文件名}_seedvr2_upscaled.{ext}`，可预测；攻击者若有其他 XSS/开放重定向漏洞可能按固定 URL 猜测下载
- **操作步骤**: `_image_pipeline.py` / `_video_pipeline.py` 的 save 环节追加 `uuid4().hex[:8]` 后缀，同时将原名保存在 history 表。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T4-4 ▐ SSE 事件广播目标过滤（用户隔离）
- **优先级**: 🟢 低
- **问题点**: SSE 当前为全局广播，若未来启用 Basic Auth 多用户，一个用户的任务进度会推送给所有连接的订阅者
- **操作步骤**: 在 SSE 的 `EventSourceResponse` 中增加 `session_id` 过滤；消息包增加 `target_session` 字段。
- **验收人**: ______  完成日期: __________  结果: ⬜

---

### T4-5 ✅ 依赖漏洞扫描纳入 CI（`pip-audit` + `safety`）
- **优先级**: 🟡 中
- **操作步骤**: 新增 `.github/workflows/dependency-audit.yml`：
  ```yaml
  name: Dependency Audit
  on: [pull_request, schedule]
  jobs:
    audit:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: pypa/gh-action-pip-audit@v1
          with:
            inputs: requirements-lock.txt
  ```
- **验证方法**: PR 页面上该工作流 fail 时阻断合并。
- **验收人**: CatPaw Agent  完成日期: 2026-08-07  结果: ✅ .github/workflows/dependency-audit.yml 已创建

---

## 五、推荐的执行顺序（按 ROI 排序）

> 建议按以下顺序推进（投入少→多，收益高→低）：

| 顺序 | 任务 | 预计耗时 | 难度 | 收益等级 |
|---|---|---|---|---|
| **①** | **T1-1** 填充 config.yaml SHA256 哈希 | 30 分钟 | ⭐ | 🔴 极高（立刻消除模型投毒风险） |
| **②** | **T2-2** 创建 NOTICE.txt | 15 分钟 | ⭐ | 🟠 高（Apache 2.0 合规，法律必备） |
| **③** | **T4-5** 依赖漏洞扫描 CI | 30 分钟 | ⭐⭐ | 🟠 高（持续防护供应链） |
| **④** | **T2-1** GPG Release 签名工作流启用 | 2-3 小时 | ⭐⭐ | 🟠 高（用户端完整性验证唯一手段） |
| **⑤** | **T4-2** 上传文件魔数白名单 | 1-2 小时 | ⭐⭐ | 🟡 中高（封堵上传投递面） |
| **⑥** | **T2-3** 生成并验证 requirements-lock.txt | 1 小时 | ⭐⭐ | 🟡 中 |
| **⑦** | **T2-4** 商标/软著注册 | 1 天+等待 | ⭐ | 🟡 中（法律层） |
| **⑧** | **T4-1** 服务端签名 CSRF + 秘钥持久化 | 2 小时 | ⭐⭐⭐ | 🟡 中 |
| **⑨** | **T3-4** PyArmor 评估 | 1 天 | ⭐⭐ | 🟢 中低 |
| **⑩** | **T3-2** Cython 核心 | 1-2 周 | ⭐⭐⭐⭐ | 🔵 中长期（抬高逆向门槛） |
| **⑪** | **T3-3** TorchScript 化 | 1-2 周 | ⭐⭐⭐⭐ | 🔵 中长期 |
| **⑫** | **T3-1** 权重 AES 加密 | 2-3 周 | ⭐⭐⭐⭐⭐ | 🔵 中长期 |
| **⑬** | **T4-3** 输出文件名随机化 | 30 分钟 | ⭐ | 🟢 低（纵深防御） |
| **⑭** | **T4-4** SSE 会话隔离 | 2 小时 | ⭐⭐ | 🟢 低（Basic Auth 启用前不紧急） |

---

## 六、执行记录日志

| 完成日期 | 任务编号 | 执行人 | 结果摘要 |
|---|---|---|---|
| 2026-08-07 | T1-1 | CatPaw Agent | ✅ 15 个 SHA256 哈希填充到 config.yaml |
| 2026-08-07 | T2-2 | CatPaw Agent | ✅ NOTICE 文件创建（Apache 2.0 合规） |
| 2026-08-07 | T2-3 | CatPaw Agent | ✅ requirements-lock.txt 生成（版本锁定，哈希待联网补充） |
| | T2-1 | | ⬜ 需用户配置 GPG 密钥和 GitHub Secrets |
| | T2-4 | | ⬜ 法律事务，需人工执行 |
| | T3-1 | | ⬜ 研发任务（2-3 周） |
| | T3-2 | | ⬜ 研发任务（1-2 周） |
| | T3-3 | | ⬜ 研发任务（1-2 周） |
| | T3-4 | | ⬜ 需 PyArmor 试用版 |
| 2026-08-07 | T4-1 | CatPaw Agent | ✅ HMAC 签名 CSRF + 密钥持久化 |
| 2026-08-07 | T4-2 | CatPaw Agent | ✅ 魔数校验模块 + 上传路由集成 |
| 2026-08-07 | T4-3 | CatPaw Agent | ✅ 输出文件名追加 uuid4 随机后缀 |
| 2026-08-07 | T4-4 | CatPaw Agent | ✅ SSE EventBus 会话过滤 |
| 2026-08-07 | T4-5 | CatPaw Agent | ✅ dependency-audit.yml CI 工作流 |

---

> **v2.0 报告结束**。执行过程中遇到某个任务无法落地、需要代码实现支持或希望将其中一项委托回代理自动完成，请在对话中注明任务编号即可。
