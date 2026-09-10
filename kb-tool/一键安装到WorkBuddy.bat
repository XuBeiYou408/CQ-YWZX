@echo off
chcp 65001 >nul
title 企业本地知识库 · WorkBuddy 一键安装助手
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 尚未检测到虚拟环境 .venv！
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" gui_installer.py
