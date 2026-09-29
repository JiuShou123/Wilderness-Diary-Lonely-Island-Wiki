@echo off
chcp 65001 >nul
title GuDao Wiki - Stop Server
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
    echo   If the server is still running in a console window, simply close it.
    echo   Otherwise, end the python.exe process from Task Manager.
    echo.
    pause
    exit /b 1
)

rem ---- Step 2. stop the running server ----
%PY% "%~dp0app\tools\serve.py" --stop

echo.
pause
