@echo off
chcp 65001 >nul
title 企业本地知识库 · 智能问答与 Agent 系统
cd /d "%~dp0"

echo ====================================================================
echo   企业本地知识库 (Enterprise Local Knowledge Base) - 正在启动...
echo ====================================================================
echo.

set "KMP_DUPLICATE_LIB_OK=TRUE"
set "CUDA_VISIBLE_DEVICES=-1"
set "PYTHONIOENCODING=utf-8"
set "HF_ENDPOINT=https://hf-mirror.com"

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
    echo [1/4] 首次运行：正在为企业知识库创建独立虚拟环境 [.venv]...
    %PY_CMD% -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [错误] 虚拟环境创建失败，请检查 Python 权限或环境配置！
        pause
        exit /b 1
    )
    echo [2/4] 首次运行：正在安装知识库依赖组件 [首次耗时较长，请稍候]...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络连接或镜像源配置！
        pause
        exit /b 1
    )
) else (
    REM 幂等检查：验证核心依赖是否完整 [fastapi, langchain]
    ".venv\Scripts\python.exe" -c "import fastapi, langchain" >nul 2>nul
    if errorlevel 1 (
        echo [提示] 检测到虚拟环境中核心依赖缺失，正在自动补齐安装...
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [错误] 依赖补齐安装失败！
            pause
            exit /b 1
        )
    )
)

REM 3. 基础目录与配置文件准备
if not exist ".env" (
    if exist ".env.example" (
        echo [配置] 正在从 .env.example 生成初始 .env 文件...
        copy /Y ".env.example" ".env" >nul
    )
)
if not exist "data\documents" mkdir "data\documents"
if not exist "data\faiss_db" mkdir "data\faiss_db"

REM 4. 检查前端静态产物
if not exist "frontend\dist\index.html" (
    echo [前端] 未检测到前端构建产物 [frontend\dist\index.html]...
    where npm >nul 2>nul
    if %errorlevel% equ 0 (
        echo [前端] 检测到 npm，正在自动构建前端界面 [耗时约 1-2 分钟]...
        pushd frontend
        call npm install
        call npm run build
        popd
    ) else (
        echo.
        echo ====================================================================
        echo [警告] 未检测到 npm 命令！
        echo 企业本地知识库前端需要 Node.js 环境构建静态产物。
        echo 请安装 Node.js [https://nodejs.org/] 并执行:
        echo   cd frontend ^&^& npm install ^&^& npm run build
        echo 当前将继续拉起后端 API 核心服务 [端口 8010]。
        echo ====================================================================
        echo.
    )
)

REM 5. 启动服务
echo [3/4] 虚拟环境与配置就绪。
echo [4/4] 正在启动企业本地知识库服务 [端口 8010]...
echo.
echo --------------------------------------------------------------------
echo   服务拉起后，系统将自动唤起浏览器: http://127.0.0.1:8010
echo --------------------------------------------------------------------
echo.

start http://127.0.0.1:8010

".venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo [提示] 知识库服务异常中断或已退出。
    pause
)
