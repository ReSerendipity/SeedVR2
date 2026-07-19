@echo off
title SeedVR2 Toolbox

:: Fix OMP duplicate library issue on Windows
set "KMP_DUPLICATE_LIB_OK=TRUE"

echo ============================================
echo   SeedVR2 Video Restoration Toolbox
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

:: Start application (isolated - no system Python interference)
cd /d "%~dp0"
"%PYTHON_CMD%" bin\clean_launch.py

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start. Check logs\app.log
    pause
)
