@echo off
chcp 65001 >nul
title social-buddy launcher

REM ============================================================
REM  One-click launcher for the social-buddy QQ bot (Windows)
REM  Edit the two paths below to match your machine, then save
REM  and double-click this file.
REM ============================================================

set NAPCAT_DIR=G:\NapCatOneKey\NapCat.52230.Shell
set BOT_DIR=G:\social-buddy

if not exist "%NAPCAT_DIR%\NapCatWinBootMain.exe" (
    echo [ERROR] NapCat not found at: %NAPCAT_DIR%
    echo Edit NAPCAT_DIR at the top of this file.
    pause
    exit /b 1
)
if not exist "%BOT_DIR%\main.py" (
    echo [ERROR] bot code not found at: %BOT_DIR%
    echo Edit BOT_DIR at the top of this file.
    pause
    exit /b 1
)

echo ========================================
echo   social-buddy QQ bot launcher
echo ========================================
echo [1/3] Starting watchdog...
start "" powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File "%NAPCAT_DIR%\..\napcat-watchdog.ps1"

echo [2/3] Waiting for services (about 20s)...
timeout /t 20 >nul

netstat -ano | findstr ":3000" >nul && echo [OK] NapCat online || echo [WARN] NapCat not detected
netstat -ano | findstr ":8765" >nul && echo [OK] Bot online || echo [WARN] Bot not detected

echo.
echo Done. Bot is online. Keep the NapCat window open.
echo This window closes in 8 seconds...
timeout /t 8 >nul
