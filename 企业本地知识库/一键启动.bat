@echo off
title 企业本地知识库 - 一键启动
color 0A

echo ====================================================================
echo         企业本地知识库 (Enterprise Local Knowledge Base)
echo ====================================================================
echo.

cd /d "%~dp0"

set "KMP_DUPLICATE_LIB_OK=TRUE"
set "CUDA_VISIBLE_DEVICES=-1"
set "PYTHONIOENCODING=utf-8"
set "HF_ENDPOINT=https://hf-mirror.com"

if not exist ".venv\Scripts\python.exe" (
    echo [提示] 尚未检测到虚拟环境 .venv，正在自动运行环境配置...
    call "%~dp0一键安装与修复环境.bat"
    if errorlevel 1 (
        echo [错误] 虚拟环境初始化失败！
        pause
        exit /b 1
    )
)

if not exist ".env" (
    if exist ".env.example" (
        echo [配置] 正在从 .env.example 生成 .env 基础配置...
        copy /Y ".env.example" ".env" >nul
    )
)

if not exist "data\documents" mkdir "data\documents"
if not exist "data\faiss_db" mkdir "data\faiss_db"

echo [1/3] 虚拟环境: .venv 就绪
echo [2/3] 数据目录: data\documents 就绪
echo [3/3] 前端大盘: frontend\dist 就绪
echo.
echo --------------------------------------------------------------------
echo 服务启动就绪后，将在浏览器中自动打开：
echo http://localhost:8010
echo --------------------------------------------------------------------
echo.

start http://localhost:8010

".venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo [提示] 服务已停止。按任意键退出...
    pause >nul
)