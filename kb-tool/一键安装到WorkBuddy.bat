@echo off
chcp 65001 >nul
title 企业本地知识库 · WorkBuddy 一键安装助手
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    rem venv 已就绪：启动图形化安装向导（注入/卸载 MCP 配置）
    start "" ".venv\Scripts\pythonw.exe" gui_installer.py
    exit /b 0
)

rem venv 不存在（首次部署/换电脑）：用系统 Python 全量安装（venv/依赖/MCP/Skill/记忆规则 + 体检）
set "PY="
where py >nul 2>nul && set "PY=py -3"
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
