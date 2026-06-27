@echo off
REM Quiet background refresh used by the scheduled task.
REM No browser, no prompts. Output is appended to refresh_log.txt.
cd /d "%~dp0"

set PYEXE=
where python >nul 2>&1 && set PYEXE=python
if "%PYEXE%"=="" ( where py >nul 2>&1 && set PYEXE=py )
if "%PYEXE%"=="" (
  echo %DATE% %TIME%  Python not found >> refresh_log.txt
  exit /b 1
)

echo ---------- %DATE% %TIME% ---------- >> refresh_log.txt
%PYEXE% fetch_engagement.py >> refresh_log.txt 2>&1
%PYEXE% publish.py >> refresh_log.txt 2>&1
