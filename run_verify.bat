@echo off
cd /d "%~dp0"

:: Detect project Python (WinPython ONLY - fully isolated)
set "PYTHON_CMD="

:: 1. Check WPy64-312101 (primary)
set "WP_DIR=%~dp0WPy64-312101"
if exist "%WP_DIR%\python\python.exe" (
    set "PYTHON_CMD=%WP_DIR%\python\python.exe"
    goto :python_found
)

:: 2. Search for any WPy64-* directory
for /d %%i in ("%~dp0WPy64-*") do (
    if exist "%%i\python\python.exe" (
        set "PYTHON_CMD=%%i\python\python.exe"
        goto :python_found
    )
)

:: 3. Search for legacy WinPython directory
set "WP_LEGACY=%~dp0WinPython"
if exist "%WP_LEGACY%\python\python.exe" (
    set "PYTHON_CMD=%WP_LEGACY%\python\python.exe"
    goto :python_found
)

:: Python not found
echo [ERROR] WinPython not found!
pause
exit /b 1

:python_found
echo Using Python: %PYTHON_CMD%
"%PYTHON_CMD%" verify_engine.py > verify_output.log 2>&1
set "VERIFY_EXIT=%ERRORLEVEL%"
type verify_output.log
if not "%VERIFY_EXIT%"=="0" (
    echo [ERROR] engine self-check failed with exit code %VERIFY_EXIT%
    exit /b %VERIFY_EXIT%
)
echo [OK] engine self-check passed
exit /b 0
