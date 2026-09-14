@echo off
chcp 65001 >nul
title 企业本地知识库 · 图形化配置助手
cd /d "%~dp0"

rem 图形化助手：卸载 / 修改路径 / 状态自检 / 端到端体检
rem 日常安装请用「一键安装到WorkBuddy.bat」（全自动、无需点击、含体检）。
rem 说明：.venv 的基础解释器可能未自带 tkinter（图形界面必需），所以这里优先挑
rem       一个「能 import tkinter」的解释器来显示界面；MCP 服务本身仍由 .venv 承载，
rem       与界面用哪个解释器无关。

set "GUIC="

if exist ".venv\Scripts\pythonw.exe" call :probe ".venv\Scripts\pythonw.exe" ".venv\Scripts\python.exe"
if defined GUIC goto run
call :probe "pyw -3" "py -3"
if defined GUIC goto run
call :probe "python" "python"
if defined GUIC goto run

echo [提示] 未找到自带 tkinter 的 Python，无法打开图形界面。
echo        这不影响使用：直接双击「一键安装到WorkBuddy.bat」即可完成全部安装与体检。
pause
exit /b 1

:run
echo 正在打开图形化配置助手...
start "" %GUIC% gui_installer.py
exit /b 0

:probe
rem %1 = 用于启动界面的解释器；%2 = 用于探测 tkinter 的控制台解释器
%2 -c "import tkinter" >nul 2>nul
if not errorlevel 1 set "GUIC=%~1"
exit /b 0
