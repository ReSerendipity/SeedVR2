@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: ---------------------------------------------------------------------------
:: One-shot local quality gate. Runs the declared checks (ruff, black, mypy,
:: pytest) through the bundled WinPython so the pyproject.toml declarations
:: have a single mechanical trigger point. Use --fast to skip mypy/pytest.
:: ---------------------------------------------------------------------------

:: Detect project Python (WinPython ONLY - fully isolated)
set "PYTHON_CMD="
set "WP_DIR=%~dp0WPy64-312101"
if exist "%WP_DIR%\python\python.exe" (
    set "PYTHON_CMD=%WP_DIR%\python\python.exe"
    goto :python_found
)
for /d %%i in ("%~dp0WPy64-*") do (
    if exist "%%i\python\python.exe" (
        set "PYTHON_CMD=%%i\python\python.exe"
        goto :python_found
    )
)
echo [ERROR] WinPython not found!
exit /b 1

:python_found
echo Using Python: %PYTHON_CMD%
set "FAILED="

echo.
echo === [1/4] ruff (lint) ===
"%PYTHON_CMD%" -m ruff check .
if errorlevel 1 set "FAILED=!FAILED! ruff"

echo.
echo === [2/4] black (format check) ===
"%PYTHON_CMD%" -m black --check .
if errorlevel 1 set "FAILED=!FAILED! black"

if /i "%~1"=="--fast" goto :report

echo.
echo === [3/4] mypy (type check) ===
"%PYTHON_CMD%" -m mypy bin/integrated_app
if errorlevel 1 set "FAILED=!FAILED! mypy"

echo.
echo === [4/4] pytest (unit, skip integration) ===
"%PYTHON_CMD%" -m pytest -q -m "not integration"
if errorlevel 1 set "FAILED=!FAILED! pytest"

:report
echo.
if defined FAILED (
    echo [RESULT] FAILED checks:!FAILED!
    exit /b 1
)
echo [RESULT] all checks passed
exit /b 0
