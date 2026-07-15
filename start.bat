@echo off
chcp 65001 >nul
title OpenCode Go Switch

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║       OpenCode Go Switch v1.0.0                      ║
echo ║       Local Proxy + Model Switcher                  ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: Find Python
set PYTHON=
for %%p in (python3 python) do (
    where %%p >nul 2>&1
    if not errorlevel 1 set PYTHON=%%p
)

if "%PYTHON%"=="" (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

:: Check if venv exists
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    echo [SETUP] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt -q
)

:: Run server
echo [START] Starting OpenCode Go Switch...
echo.
venv\Scripts\python server.py

pause
