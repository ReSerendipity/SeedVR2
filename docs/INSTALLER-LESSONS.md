# SeedVR2-lite 桌面安装包（exe）经验教训清单

> 本文件集中记录 Windows 桌面安装包从打包、发布到首启 Torch 安装过程中遇到的
> 真实问题与解决结论，全部经过实测，供后续迭代与复用（与 `CI-LESSONS.md` 的
> CI/测试经验互补，这里聚焦"打成 exe + 用户首启安装"）。

## 0. 一句话总览

- 桌面 exe 生命周期：**本地零构建**，全靠 GitHub Actions 云端打 tag 触发构建。
- 安装包不内置 torch（CUDA wheel ~2.7GB 超 GitHub 单文件 2GiB 限制），
  由**首启引导页**下载安装。
- 国内镜像装 torch 的坑：`--index-url` 解析不了 `%2Bcu128`，必须改用
  `--find-links` + 显式版本约束。

## A. 打包与发布（构建侧）

1. **本地不构建**：WinPython / 7-Zip / Inno Setup / PyInstaller 都在云端
   （`desktop-release.yml`）准备，本地只 `dist/SeedVR2.exe` 一个启动器中间
   产物。不要到本地重复下载/装工具链。
2. **触发方式 = push tag `v*`**：`desktop-release.yml` 只在 tag 推送事件触发。
   手动本地想触发需 `git tag -f vX.Y.Z origin/main; git push --force origin vX.Y.Z`
   （把 tag 移到最新 main 再强制推送，本地 tag 即使被拒绝 stale info 也别慌，
   用 `--force` 覆盖即可）。
3. **版本号来源**：tag 名 `v1.3.0` → `1.3.0`；workflow_dispatch（无 tag）时回退读
   `pyproject.toml` 的 `version`。两处没对齐会导致安装包版本号与预期不符。
4. **release 可能已被 release-please 自动创建**（空、0 资产）。此时不用新建
   release，直接把 tag 指到要发布的 commit 再 push，CI 会向已存在的同名
   release 上传资产并自动写发布说明（复用 `launcher/release-notes-intro.md`）。
5. **GitHub release 单附件上限 2GiB**：torch CUDA wheel 2.7GB 不能内置，这是
   "安装包只含【便携 Python + 应用 + 小依赖】，torch 首启装" 的根本原因。
6. **安装包体积**：`SeedVR2-Setup-<ver>.exe` 约 165MB（含 WinPython + 小依赖，
   不含 torch）。别把 torch/torchvision/torchaudio 预装进便携 Python，否则
   膨胀到 3GB+ 且超限（`installer.iss` 里不包含它们的独立 Source）。
7. **SHA256SUMS**：随包生成，发布单个 exe + SHA256SUMS 即可，供进阶用户校验。

## B. Torch 首启安装（运行时侧，本文件重点）

### B.1 镜像源的坑（用户反馈：阿里云报"找不到"退出码 1）

8. **根因**：CUDA wheel 镜像（阿里云/清华 `pytorch-wheels`）目录里的文件名是
   URL 编码形式（`torch-2.11.0%2Bcu128-...whl`）。pip 的 `--index-url`
   （PEP 503 简单索引）无法把 `%2B` 还原成 `+cu128` 本地版本号，于是报
   `No matching distribution found for torch`——**文件明明存在，却匹配不到**。
9. **正确解法**：国内镜像改用 **`--find-links <镜像目录> --no-index`**（直接浏览
   目录列出具体 WHL，绕过简单索引解析），官方源才用 `--index-url`。
10. **必须显式版本约束**：`--find-links` 目录同时含 CPU 版（无 `+cuXXX`）与
    CUDA 版时，pip 默认优先选 CPU 版（版本号更高）→ 装上的是 CPU 版，GPU 用
    不了。所以包名要写成 `torch==2.11.0+cu128`（带 `+<cuda>` 后缀），拒绝无核对
    裸包名。实测：`torch==2.11.0+cu128` 精确匹配到 2.7GB 的 CUDA win_amd64 wheel。

### B.2 URL 验证要点

11. 验证连通性/会不会选错版，用 **`pip install --dry-run --find-links ...`**，
    看输出是否出现 `Collecting torch==x.y.z+cuXXX` 与对应 WHL 大小，**联通即可，
    不要等它下载完 2.7GB**（看到开始 Downloading 大文件后及时 Ctrl-C / Stop）。
12. 疑似镜像"失效"先 curl / WebFetch 目录列表确认文件真的在，别急着换源——常见
    是解析问题不是文件缺失。

### B.3 CUDA 档位 / 版本锁定

13. **cu128 不是 torch 版本，是 CUDA 12.8 预编译档**。torch 具体版本可自选（同一
    档里 pip 取最新）。真正的硬约束是**驱动（`nvidia-smi` 显示的 CUDA Version）要
    ≥ 该档位**。
14. 驱动版本较老时，界面需提供更低的档位：**cu118 / cu121 / cu126 / cu128**，
    由环境检测读取驱动 CUDA 版本自动推荐并默认选中。档位→torch 版本映射放在
    `TORCH_CUDA_VERSIONS` 一处维护，升级只改这一处。
15. torchvision / torchaudio 必须**同源同装（同一 index/镜像 + 同 `+cuXXX` 后缀）**
    且版本与 torch 严格配套（如 torch 2.11.0 → torchvision 0.28.0），否则 import
    失败或 CUDA 不识别。

### B.4 "跳过"为什么被强制

16. "跳过此步"是**防呆设计**而非 bug：只有**检测到已可用的 torch 环境**（如已有
    `.venv` / 系统已装 torch）才放行；torch 真没装时拒绝跳过，避免后续冒烟测试在
    无 GPU/无 torch 下静默失败。报错信息会给出探测详情，用户需先解决环境或选对
    源安装。

## C. 版本查询 / 发布节奏（复用）

17. 发布前用 `gh release view vX.Y.Z --json assets` 确认资产是否已上传；发布用
    `gh release upload <tag> <file>`，或交给 tag 触发的 CI 自动上传。
18. 每次修复记得：改源码 → 补/改单测（`test_launcher_dependency_check.py` 等）
    → 本地跑绿 launcher 相关测试 → 提交 → 打新 tag → CI 重新构建发布。
19. 注意 test collection 里非安装包相关的环境错误（如 `No module named 'bin'`）
    是 CI 完整环境下才有的路径问题，本地没有属正常；以受影响模块的测试为准。

## D. 关键文件地图（改什么去哪）

| 关注点 | 文件 |
|---|---|
| 安装源/命令、CUDA 档位映射 | `launcher/dependency_check.py` |
| 环境检测附推荐的源 | `launcher/bootstrap_server.py` |
| 镜像下拉选项（前端） | `launcher/static/index.html` |
| 自动选中推荐源（前端） | `launcher/static/app.js` |
| 打包脚本 | `launcher/installer.iss` |
| 发布 CI | `.github/workflows/desktop-release.yml` |
| 发布说明模板 | `launcher/release-notes-intro.md` |
| 相关单测 | `tests/test_launcher_dependency_check.py` 等 |