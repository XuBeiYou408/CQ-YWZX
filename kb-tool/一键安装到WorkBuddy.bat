@echo off
chcp 65001 >nul
title 企业本地知识库 · WorkBuddy 一键安装
cd /d "%~dp0"

rem 统一走完整幂等安装（venv/依赖 -> mcp.json -> 路由 Skill -> 记忆规则 -> 端到端体检）。
rem 注意：无论 venv 是否已存在都执行同一条路径，这样 Skill 与记忆规则会随项目更新一起下发
rem       （旧版在 venv 存在时改走图形向导，会漏装 Skill）。
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
echo 如需卸载、修改路径或做状态自检，请双击本目录下的「图形化配置助手.bat」。
pause
