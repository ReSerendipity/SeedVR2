@echo off
REM Flash Attention 安装脚本 (Windows + CUDA)
REM 自动检测 CUDA 版本并安装匹配的预编译包

echo ========================================
echo Flash Attention 2 安装脚本
echo ========================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] Python 未安装
    exit /b 1
)

REM 检查 CUDA
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 NVIDIA 驱动
    echo 请先安装 NVIDIA 驱动
    exit /b 1
)

echo [信息] 检测 CUDA 版本...
nvidia-smi --query-gpu=driver_version --format=csv,noheader
nvcc --version 2>nul | findstr "release"

REM 检查 PyTorch CUDA
python -c "import torch; print(f'PyTorch CUDA: {torch.version.cuda}')" 2>nul
if errorlevel 1 (
    echo [警告] PyTorch 未安装
    echo 正在安装 PyTorch (CUDA 12.1)...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
)

REM 获取 PyTorch CUDA 版本
for /f "tokens=*" %%i in ('python -c "import torch; print(torch.version.cuda.replace('.', ''))"') do set TORCH_CUDA=%%i
echo [信息] PyTorch CUDA 版本: %TORCH_CUDA%

REM 尝试安装预编译 flash-attn
echo [信息] 尝试安装 flash-attn 预编译包...
pip install flash-attn --no-build-isolation 2>nul
if errorlevel 1 (
    echo [警告] 预编译包安装失败，尝试从源码编译...
    echo [信息] 这可能需要 10-30 分钟...
    pip install flash-attn==2.5.0 --no-build-isolation
    if errorlevel 1 (
        echo [错误] 源码编译也失败
        echo 常见原因:
        echo   1. CUDA Toolkit 未安装
        echo   2. 编译器版本不匹配
        echo   3. 显存不足
        echo.
        echo 替代方案:
        echo   pip install xformers  # 备选注意力库
        exit /b 1
    )
)

echo ========================================
echo [成功] Flash Attention 2 安装完成！
echo ========================================
python -c "from flash_attn import flash_attn_qkvpacked_func; print('验证通过')"

REM 运行性能测试
echo.
echo 是否运行性能测试？ (Y/N)
set /p RUN_BENCH=
if /i "%RUN_BENCH%"=="Y" (
    python perf\benchmark\flash_attn_benchmark.py
)
