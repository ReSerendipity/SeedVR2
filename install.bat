@echo off
title SeedVR2 Toolbox - Setup

echo ============================================
echo   SeedVR2 Video Restoration Toolbox - Setup
echo ============================================
echo.

:: Detect project Python (WinPython ONLY - fully isolated)
set "PYTHON_CMD="

:: 1. Check WPy64-312101 (primary)
set "WP_DIR=%~dp0WPy64-312101"
if exist "%WP_DIR%\python\python.exe" (
    set "PYTHON_CMD=%WP_DIR%\python\python.exe"
    echo [OK] Found WinPython 3.12.10
    goto :python_found
)

:: 2. Search for any WPy64-* directory
for /d %%i in ("%~dp0WPy64-*") do (
    if exist "%%i\python\python.exe" (
        set "PYTHON_CMD=%%i\python\python.exe"
        echo [OK] Found WinPython
        goto :python_found
    )
)

:: 3. Search for WinPython64-* directory (plan naming)
for /d %%i in ("%~dp0WinPython64-*") do (
    for /d %%j in ("%%i\python-*.amd64") do (
        if exist "%%j\python.exe" (
            set "PYTHON_CMD=%%j\python.exe"
            echo [OK] Found WinPython
            goto :python_found
        )
    )
)

:: 4. Search for legacy WinPython directory
set "WP_LEGACY=%~dp0WinPython"
if exist "%WP_LEGACY%\python\python.exe" (
    set "PYTHON_CMD=%WP_LEGACY%\python\python.exe"
    echo [OK] Found WinPython (legacy)
    goto :python_found
)

:: Python not found - show error
echo [ERROR] WinPython not found in project directory!
echo.
echo Please download and extract WinPython to the project directory:
echo   Expected: %~dp0WPy64-312101\python\python.exe
echo.
echo Download from: https://github.com/winpython/winpython/releases
echo Or run: scripts\setup_winpython.py
echo.
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

:: Install PyTorch with CUDA support first
echo.
echo [Install] Installing PyTorch with CUDA support...
"%PYTHON_CMD%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 --timeout 600 --retries 5

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
