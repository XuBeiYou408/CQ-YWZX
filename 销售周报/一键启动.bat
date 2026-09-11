@echo off
chcp 65001 >nul
title SalesAgent · 企业销售周报自动汇总智能体
cd /d "%~dp0"

echo ====================================================================
echo   SalesAgent · 企业销售周报自动汇总智能体 - 正在启动...
echo ====================================================================
echo.

REM 1. 寻找可用的 Python 3 解释器（优先 py -3，次选 python，防御微软商店占位符）
set "PY_CMD="
py -3 -c "import sys; exit(0 if sys.version_info[0]==3 else 1)" >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"

if not defined PY_CMD (
    python -c "import sys; exit(0 if sys.version_info[0]==3 else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo.
    echo ====================================================================
    echo [错误] 未在系统中检测到可用的 Python 3 解释器！
    echo 建议安装 Python 3.11 - 3.13: https://www.python.org/downloads/
    echo [!] 安装时请务必勾选:
    echo   [x] "Add Python to PATH"
    echo   [x] "Install launcher for all users (py)"
    echo ====================================================================
    echo.
    pause
    exit /b 1
)

REM 2. 检查或自动自举初始化本项目专属虚拟环境 [.venv]
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 首次运行：正在为销售周报项目创建独立虚拟环境 [.venv]...
    %PY_CMD% -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [错误] 虚拟环境创建失败，请检查 Python 权限或环境配置！
        pause
        exit /b 1
    )
    echo [2/3] 首次运行：正在安装本项目所需依赖组件 [请稍候]...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络连接！
        pause
        exit /b 1
    )
) else (
    REM 幂等检查：验证核心依赖是否完整 [fastapi, docx, openpyxl, multipart, httpx]
    ".venv\Scripts\python.exe" -c "import fastapi, docx, openpyxl, multipart, httpx" >nul 2>nul
    if errorlevel 1 (
        echo [提示] 检测到虚拟环境中存在缺失依赖，正在自动补齐安装...
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [错误] 依赖补齐安装失败！
            pause
            exit /b 1
        )
    )
)

REM 3. 启动服务
echo [3/3] 虚拟环境就绪，正在启动 SalesAgent 驾驶舱 [端口 8040]...
echo.
".venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo [提示] SalesAgent 服务异常中断或已退出。
    pause
)
