@echo off
chcp 65001 >nul
title GuDao Wiki - Local Server
cd /d "%~dp0"

rem ---- Force UTF-8 I/O so that Chinese output stays readable ----
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem ---- Step 1. locate a working Python 3 ----
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    py -c "import sys" >nul 2>nul && set "PY=py"
)

if not defined PY (
    echo.
    echo   [ERROR] Python 3 was not found on this computer.
    echo.
    echo   Please install Python 3 first:
    echo       https://www.python.org/downloads/
    echo   Remember to check "Add python.exe to PATH" during installation,
    echo   then double-click this file again.
    echo.
    pause
    exit /b 1
)

rem ---- Step 2. start the local server (it opens the browser automatically) ----
%PY% "%~dp0app\tools\serve.py" %*

if errorlevel 1 (
    echo.
    echo   [ERROR] The server could not start. Please check the messages above.
    echo.
    pause
)
