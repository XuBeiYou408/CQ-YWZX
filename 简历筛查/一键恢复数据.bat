@echo off
chcp 936 >nul
title RecruitAI · 一键恢复数据（开发自测专用）
cd /d "%~dp0"

set "PORT=8030"
set "BASELINE=%~dp0data\store.baseline.json"
set "STORE=%~dp0data\store.json"
set "BACKUP_DIR=%~dp0data\backup"
set "PYEXE=%~dp0.venv\Scripts\python.exe"

echo ====================================================================
echo   RecruitAI · 一键恢复数据（开发自测专用）
echo --------------------------------------------------------------------
echo   用途：反复上传同一份简历测试各业务模块时，每测完一轮执行本脚本，
echo         即可把 候选人库 / 人才公海 / 面试日程 / 微聊记录 / 淘汰拒信
echo         全量还原为约定的干净初始状态，便于下一轮回归测试。
echo ====================================================================
echo.

if not exist "%BASELINE%" goto NO_BASELINE

REM ---------- 1. backup current data (keep latest 10) ----------
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%" >nul 2>nul
set "TS="
for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%t"
if not defined TS set "TS=manual"
if exist "%STORE%" copy /y "%STORE%" "%BACKUP_DIR%\store_%TS%.json.bak" >nul 2>nul
if exist "%BACKUP_DIR%\store_%TS%.json.bak" echo [1/3] 当前数据已备份至 data\backup\store_%TS%.json.bak
if not exist "%BACKUP_DIR%\store_%TS%.json.bak" echo [1/3] 未发现 data\store.json，跳过备份（将直接生成干净数据）
for /f "skip=10 delims=" %%F in ('dir /b /a-d /o-d "%BACKUP_DIR%\*.json.bak" 2^>nul') do del /q "%BACKUP_DIR%\%%F" >nul 2>nul

REM ---------- 2. restore: sync running service, else file-level ----------
netstat -ano | findstr /c:":%PORT% " | findstr /c:"LISTENING" >nul 2>nul
if errorlevel 1 goto FILE_RESTORE

echo [2/3] 检测到 RecruitAI 服务正在运行（端口 %PORT%），正在通知服务同步重置内存数据...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{ Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/api/reset' -Method Post -TimeoutSec 20 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 goto API_FAIL
set "RESTORED=api"
echo       服务内存数据已同步重置完成。
goto VERIFY

:API_FAIL
echo       [警告] 运行中的服务未响应重置接口（可能仍是旧版本代码），改走文件级恢复。
echo              如需内存同步，请重启服务后再执行本脚本。

:FILE_RESTORE
echo [2/3] 正在执行文件级数据恢复...
copy /y "%BASELINE%" "%STORE%" >nul
if errorlevel 1 goto COPY_FAIL
set "RESTORED=file"

REM ---------- 3. verify restored data ----------
:VERIFY
echo [3/3] 正在校验恢复结果...
if not exist "%PYEXE%" goto VERIFY_NOPY
"%PYEXE%" -c "import json;d=json.load(open('data/store.json',encoding='utf-8'));print('      candidates='+str(len(d['candidates']))+'  pool='+str(len(d['talent_pool']))+'  interviews='+str(len(d['interviews']))+'  chats='+str(len(d['chat_history']))+'  rejections='+str(len(d['rejections'])))"
goto VERIFY_TAIL

:VERIFY_NOPY
echo       [提示] 未找到 .venv 虚拟环境，跳过数据统计校验。

:VERIFY_TAIL
echo       初始状态基准：候选人 4 / 公海 4 / 面试日程 1 / 沟通 4 / 拒信 0
echo.
echo ====================================================================
if "%RESTORED%"=="api" goto DONE_API
echo   [完成] 数据已恢复为初始状态（文件级还原）。
echo          若服务正在运行，请重启服务后再刷新页面以加载干净数据。
goto DONE_TAIL

:DONE_API
echo   [完成] 数据已恢复为初始状态，运行中的服务内存已同步刷新。
echo          现在直接刷新浏览器页面即可开始新一轮测试。

:DONE_TAIL
echo --------------------------------------------------------------------
echo   测试闭环：刷新工作台 -^> 上传同一份简历 -^> 验证各业务模块 -^> 再执行本脚本
echo   备份位置：data\backup\（自动保留最近 10 份恢复前数据）
echo ====================================================================
echo.
pause
exit /b 0

:NO_BASELINE
echo [错误] 未找到基线快照文件：data\store.baseline.json
echo        刷新方法：在干净状态下执行  copy /y data\store.json data\store.baseline.json
echo.
pause
exit /b 1

:COPY_FAIL
echo.
echo [错误] 数据恢复失败：无法写入 data\store.json（文件可能被占用或只读）
echo.
pause
exit /b 1
