@echo off
chcp 65001 >nul
title SalesAgent · 企业销售周报自动汇总智能体
cd /d "%~dp0"
echo ========================================================
echo   SalesAgent 销售周报自动汇总智能体 - 正在启动...
echo ========================================================
python run.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动异常中断，按任意键退出...
    pause >nul
)