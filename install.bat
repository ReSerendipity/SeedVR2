@echo off
title SeedVR2 Toolbox - Setup

echo ============================================
echo   SeedVR2 Video Restoration Toolbox - Setup
echo ============================================
echo.

:: Detect Python interpreter (prefer system Python, fallback to bundled WinPython)
set "PYTHON_CMD="

:: ============================================================
:: 1. First, try system Python (preferred)
:: ============================================================

:: 1a. Check common system Python installation paths
if exist "C:\Python312\python.exe" (
    set "PYTHON_CMD=C:\Python312\python.exe"
    echo [OK] Found system Python: C:\Python312\python.exe
    goto :python_found
)

if exist "C:\Python311\python.exe" (
    set "PYTHON_CMD=C:\Python311\python.exe"
    echo [OK] Found system Python: C:\Python311\python.exe
    goto :python_found
)

if exist "C:\Program Files\Python312\python.exe" (
    set "PYTHON_CMD=C:\Program Files\Python312\python.exe"
    echo [OK] Found system Python: C:\Program Files\Python312\python.exe
    goto :python_found
)

if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    echo [OK] Found system Python (user-level)
    goto :python_found
)

:: 1b. Try PATH via `where python` - get the first one that's NOT in TRAE/IDE directories
for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "TRAE" >nul
    if errorlevel 1 (
        echo %%i | findstr /i "IDE" >nul
        if errorlevel 1 (
            set "PYTHON_CMD=%%i"
            echo [OK] Found system Python in PATH: %%i
            goto :python_found
        )
    )
)

:: ============================================================
:: 2. Fallback to bundled WinPython (legacy isolated mode)
:: ============================================================

:: 2a. Check WPy64-312101 (primary WinPython)
set "WP_DIR=%~dp0WPy64-312101"
if exist "%WP_DIR%\python\python.exe" (
    set "PYTHON_CMD=%WP_DIR%\python\python.exe"
    echo [OK] Found bundled WinPython 3.12.10
    goto :python_found
)

:: 2b. Search for any WPy64-* directory
for /d %%i in ("%~dp0WPy64-*") do (
    if exist "%%i\python\python.exe" (
        set "PYTHON_CMD=%%i\python\python.exe"
        echo [OK] Found bundled WinPython
        goto :python_found
    )
)

:: 2c. Search for WinPython64-* directory
for /d %%i in ("%~dp0WinPython64-*") do (
    for /d %%j in ("%%i\python-*.amd64") do (
        if exist "%%j\python.exe" (
            set "PYTHON_CMD=%%j\python.exe"
            echo [OK] Found bundled WinPython
            goto :python_found
        )
    )
)

:: 2d. Search for legacy WinPython directory
set "WP_LEGACY=%~dp0WinPython"
if exist "%WP_LEGACY%\python\python.exe" (
    set "PYTHON_CMD=%WP_LEGACY%\python\python.exe"
    echo [OK] Found bundled WinPython (legacy)
    goto :python_found
)

:: ============================================================
:: 3. No Python found at all
:: ============================================================
echo [ERROR] Python interpreter not found!
echo.
echo ============================================================
echo   You have two options:
echo ============================================================
echo.
echo   Option A (Recommended) - Use system Python:
echo     1. Install Python 3.12+ from https://www.python.org/downloads/
echo        Make sure to check "Add Python to PATH" during installation.
echo     2. Verify: open Command Prompt and run: python --version
echo     3. Then re-run install.bat
echo.
echo   Option B - Use bundled WinPython (isolated):
echo     1. Download WinPython from:
echo        https://github.com/winpython/winpython/releases
echo     2. Extract to project directory so this exists:
echo        %~dp0WPy64-312101\python\python.exe
echo     3. Or run: python scripts\setup_winpython.py
echo     4. Then re-run install.bat
echo.
echo ============================================================
pause
exit /b 1

:python_found
echo Using Python: %PYTHON_CMD%
echo.

:: Check Python version
"%PYTHON_CMD%" --version
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

:: Check VC++ Runtime
echo.
echo [Check] Visual C++ Runtime...
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Version >nul 2>&1
if errorlevel 1 (
    echo [!] VC++ Runtime not detected. Recommended to install.
    echo     Run: VC_redist\VC_redist.x64.exe
    echo.
    set /p INSTALL_VC="Install now? (Y/N): "
    if /i "%INSTALL_VC%"=="Y" (
        if exist "%~dp0VC_redist\VC_redist.x64.exe" (
            start "" "%~dp0VC_redist\VC_redist.x64.exe"
            echo Please re-run this script after installation
            pause
            exit /b 0
        ) else (
            echo [!] VC_redist.x64.exe not found. Please download manually.
        )
    )
) else (
    echo [OK] VC++ Runtime installed
)

:: Install PyTorch with CUDA support first (CUDA 13.2)
echo.
echo [Install] Installing PyTorch with CUDA 13.2 support...
echo          If download is too slow, download the .whl files manually:
echo          torch-2.13.0+cu132: https://download-r2.pytorch.org/whl/cu132/torch-2.13.0%%2Bcu132-cp312-cp312-win_amd64.whl
echo          torchvision-0.28.0+cu132: https://download-r2.pytorch.org/whl/cu132/torchvision-0.28.0%%2Bcu132-cp312-cp312-win_amd64.whl
echo          Then install locally: pip install torch-*.whl torchvision-*.whl torchaudio
echo          NOTE: torchaudio displays "+cpu" tag - this is NORMAL. Official cu132
echo          index has no Windows cp312 torchaudio build. GPU support comes from
echo          the underlying torch+cu132 and has been verified working.
echo.
"%PYTHON_CMD%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu132 --timeout 1200 --retries 10

:: Install other dependencies
echo.
echo [Install] Installing Python dependencies...
"%PYTHON_CMD%" -m pip install -r "%~dp0requirements.txt" --timeout 300 --retries 3

if errorlevel 1 (
    echo [WARN] Some dependencies failed to install
)

echo.
echo ============================================
echo   Installation complete!
echo   Run start.bat to launch the application
echo ============================================
pause
