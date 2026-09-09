@echo off
chcp 65001 >nul
title RecruitAI · 企业智能招聘与简历初筛工作台
cd /d "%~dp0"
echo ========================================================
echo   RecruitAI 智能招聘与简历筛查智能体 - 正在启动...
echo ========================================================
python run.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动异常中断，按任意键退出...
    pause >nul
)
