@echo off
title SeedVR2 Database Backup
setlocal enabledelayedexpansion

:: SeedVR2 数据库备份脚本 (Windows)
:: 备份 SQLite 历史数据库 + 输出目录 + 上传目录
::
:: Usage:
::   scripts\backup-db.bat [backup_dir]
::
:: 默认备份到 backups\ 目录

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
cd /d "%PROJECT_ROOT%"

:: 备份目录
if "%~1"=="" (
    set "BACKUP_DIR=backups"
) else (
    set "BACKUP_DIR=%~1"
)

:: 时间戳
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "TIMESTAMP=%dt:~0,8%_%dt:~8,6%"
set "BACKUP_PATH=%BACKUP_DIR%\seedvr2_backup_%TIMESTAMP%"

echo ============================================
echo   SeedVR2 数据库备份
echo ============================================
echo   项目路径: %PROJECT_ROOT%
echo   备份路径: %BACKUP_PATH%
echo   时间戳:   %TIMESTAMP%
echo.

:: 创建备份目录
mkdir "%BACKUP_PATH%" 2>nul
mkdir "%BACKUP_DIR%" 2>nul

:: 1. 备份 SQLite 数据库
echo [1/4] 备份 SQLite 历史数据库...
if exist "data\history.db" (
    copy "data\history.db" "%BACKUP_PATH%\history.db" >nul
    echo   [OK] history.db 已备份
) else (
    echo   [SKIP] history.db 不存在
)

:: 2. 备份配置文件
echo [2/4] 备份配置文件...
if exist "config.yaml" (
    copy "config.yaml" "%BACKUP_PATH%\config.yaml" >nul
    echo   [OK] config.yaml 已备份
)
if exist ".env" (
    copy ".env" "%BACKUP_PATH%\.env.backup" >nul
    echo   [OK] .env 已备份
)

:: 3. 备份输出目录
echo [3/4] 备份输出目录...
if exist "outputs" (
    xcopy "outputs" "%BACKUP_PATH%\outputs" /E /I /Q >nul
    echo   [OK] outputs\ 已备份
) else (
    echo   [SKIP] outputs\ 不存在
)

:: 4. 备份上传目录
echo [4/4] 备份上传目录...
if exist "data\uploads" (
    xcopy "data\uploads" "%BACKUP_PATH%\uploads" /E /I /Q >nul
    echo   [OK] data\uploads\ 已备份
) else (
    echo   [SKIP] data\uploads\ 不存在
)

:: 压缩备份（使用 PowerShell）
echo.
echo [压缩] 创建 zip 压缩包...
set "ARCHIVE=%BACKUP_DIR%\seedvr2_backup_%TIMESTAMP%.zip"
powershell -Command "Compress-Archive -Path '%BACKUP_PATH%\*' -DestinationPath '%ARCHIVE%' -Force"
if exist "%ARCHIVE%" (
    echo   [OK] 压缩包: %ARCHIVE%
) else (
    echo   [WARN] 压缩失败，保留未压缩的备份目录
)

:: 清理未压缩的临时目录
if exist "%ARCHIVE%" (
    rmdir /S /Q "%BACKUP_PATH%" 2>nul
)

:: 清理旧备份（保留最近 7 天）
echo.
echo [清理] 删除 7 天前的旧备份...
forfiles /P "%BACKUP_DIR%" /M "seedvr2_backup_*.zip" /D -7 /C "cmd /c del @path" 2>nul
if %errorlevel%==0 (
    echo   [OK] 旧备份清理完成
) else (
    echo   [INFO] 没有需要清理的旧备份
)

echo.
echo ============================================
echo   备份完成！
echo ============================================
pause
