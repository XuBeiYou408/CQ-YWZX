@echo off
chcp 65001 >nul
title Contract Reviewer (contract-reviewer) - WorkBuddy One-Click Install
cd /d "%~dp0"

rem Prefer the project .venv; if it is missing (first deploy / new machine) fall
rem   back to full install with the system Python. Both paths are idempotent.

rem Interpreter detection: confirm by ACTUALLY RUNNING it, not by `where`.
rem Reason: a fresh Windows ships a Microsoft Store python.exe alias that sits on
rem   PATH but always fails, so `where` would wrongly report "Python found".
rem KEEP THIS FILE ASCII-ONLY. Non-ASCII bytes in a .bat make cmd.exe desync its
rem   read offset and execute fragments as commands (reproduced on this machine).
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] No usable Python found.
    echo         Please install Python 3.10+ ^(3.12 / 3.13 recommended^) and tick
    echo         "Add python.exe to PATH" during setup:
    echo           https://www.python.org/downloads/windows/
    echo         Then double-click this file again.
    pause
    exit /b 1
)

%PY% install_to_workbuddy.py
echo.
pause
