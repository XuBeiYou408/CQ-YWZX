@echo off
title 企业本地知识库 - 虚拟环境安装与自愈向导
color 0B

echo ====================================================================
echo         企业本地知识库 - 自动化虚拟环境向导
echo ====================================================================
echo.

cd /d "%~dp0"
set "HF_ENDPOINT=https://hf-mirror.com"
set "PYTHONIOENCODING=utf-8"

where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo [检测] 发现 uv 极速包管理器，使用 uv 快速构建虚拟环境...
    echo [创建] 正在创建专属虚拟环境 .venv ...
    uv venv --python 3.12 .venv
    if errorlevel 1 (
        uv venv .venv
    )
    echo [安装] 正在高速安装依赖清单 (requirements.txt)...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe
    goto CHECK_FE
)

set "PY_CMD="
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=py -3.12"
    py -3.12 -V >nul 2>nul
    if errorlevel 1 (
        set "PY_CMD=py"
    )
)

if "%PY_CMD%"=="" (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

if "%PY_CMD%"=="" (
    echo.
    echo ====================================================================
    echo [提示] 当前电脑未检测到已安装的 Python 解释器！
    echo 推荐安装方式：
    echo 1. 前往 Python 官网下载安装 Python 3.11 或 3.12 64-bit
    echo    下载地址: https://www.python.org/downloads/
    echo    ★ 安装时务必勾选 "Add python.exe to PATH"（添加到环境变量）！
    echo ====================================================================
    echo.
    pause
    exit /b 1
)

echo [检测] 检测到系统 Python: %PY_CMD%
echo [创建] 正在创建专属虚拟环境 .venv ...
%PY_CMD% -m venv .venv
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败！
    pause
    exit /b 1
)

echo [安装] 正在安装 Python 依赖项 (国内清华源高速通道)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 部分依赖安装遇到提示，尝试官方源补齐...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

:CHECK_FE
echo [前端] 检查前端静态资源...
if not exist "frontend\dist\index.html" (
    where npm >nul 2>nul
    if %errorlevel% equ 0 (
        echo [编译] 正在编译前端界面...
        cd frontend
        call npm install
        call npm run build
        cd ..
    )
)

echo.
echo ====================================================================
echo   环境配置与校验完成！
echo   现在您可以直接双击运行【一键启动.bat】开启企业本地知识库！
echo ====================================================================
echo.
pause