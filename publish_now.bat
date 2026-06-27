@echo off
REM Force an immediate refresh + web publish (ignores the throttle).
REM Use this when you want leadership to see the very latest right away.
cd /d "%~dp0"

set PYEXE=
where python >nul 2>&1 && set PYEXE=python
if "%PYEXE%"=="" ( where py >nul 2>&1 && set PYEXE=py )
if "%PYEXE%"=="" ( echo Python not found. & pause & exit /b 1 )

echo Fetching the latest data...
%PYEXE% fetch_engagement.py
echo.
echo Publishing to the web now...
%PYEXE% publish.py --force
echo.
pause
