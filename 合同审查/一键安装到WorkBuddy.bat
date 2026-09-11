@echo off
chcp 65001 >nul
title 合同审查 · WorkBuddy 一键安装
cd /d "%~dp0"

rem 优先用项目 venv；venv 不存在（首次部署）则用系统 Python 全量安装
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [错误] 未找到 Python。请先安装 Python 3.10+ 并勾选 "Add to PATH" 后重试。
    pause
    exit /b 1
)

%PY% install_to_workbuddy.py
echo.
pause
