@echo off
chcp 65001 >nul
title Enterprise KB - GUI config helper
cd /d "%~dp0"

rem GUI helper: uninstall / change install path / status self-check / self-test.
rem For daily install just use the one-click install bat (fully automatic).
rem The .venv base interpreter may not ship tkinter (required by the GUI), so we
rem   pick the first interpreter that can "import tkinter" to show the window.
rem   The MCP service itself is still served by .venv, independent of the GUI.
rem KEEP THIS FILE ASCII-ONLY. Non-ASCII bytes in a .bat make cmd.exe desync its
rem   read offset and execute fragments as commands (reproduced on this machine).

set "GUIC="

if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" -c "import tkinter" >nul 2>nul && set "GUIC=.venv\Scripts\pythonw.exe"
)
if not defined GUIC (
    pyw -3 -c "import tkinter" >nul 2>nul && set "GUIC=pyw -3"
)
if not defined GUIC (
    py -3 -c "import tkinter" >nul 2>nul && set "GUIC=py -3"
)
if not defined GUIC (
    python -c "import tkinter" >nul 2>nul && set "GUIC=python"
)
if not defined GUIC (
    echo [ERROR] No Python with tkinter found, cannot open the GUI.
    echo         This does not block you: just double-click the one-click install
    echo         bat in this folder to finish setup ^(automatic, with self-check^).
    pause
    exit /b 1
)

start "" %GUIC% gui_installer.py
exit /b 0
