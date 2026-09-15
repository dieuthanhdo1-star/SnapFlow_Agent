@echo off
chcp 65001 >nul
title SnapFlow - Startup
cd /d "%~dp0"
echo ==================================================
echo SnapFlow starting. Please keep this window open.
echo An available local port will be selected automatically.
echo ==================================================
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 -u launcher.py
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python 3.10 or newer.
    ) else (
        python -u launcher.py
    )
)
echo.
echo Startup finished. If the page is blank, copy the messages above.
pause
