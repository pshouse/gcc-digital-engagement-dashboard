@echo off
REM ===========================================================
REM  Gaston Community Church - Engagement Dashboard refresh
REM  Double-click this file to pull the latest numbers.
REM ===========================================================
cd /d "%~dp0"

REM Use ONE interpreter for both install and run (prefer python, then py)
set PYEXE=
where python >nul 2>&1 && set PYEXE=python
if "%PYEXE%"=="" ( where py >nul 2>&1 && set PYEXE=py )

if "%PYEXE%"=="" (
  echo.
  echo Python was not found on this computer.
  echo Install it once from https://www.python.org/downloads/  ^(check "Add to PATH"^)
  echo or from the Microsoft Store ^(search "Python 3"^), then run this again.
  echo.
  pause
  exit /b 1
)

echo Using interpreter:
%PYEXE% -c "import sys; print('   ', sys.executable)"
echo.

echo Installing / updating required libraries into THAT interpreter...
%PYEXE% -m pip install --upgrade google-analytics-data google-auth google-auth-oauthlib google-api-python-client requests

echo.
echo Verifying libraries are visible to the interpreter...
%PYEXE% -c "import google.analytics.data_v1beta, googleapiclient, requests; print('   all libraries OK')" || echo    *** LIBRARY CHECK FAILED - copy the lines above and send them to Claude ***

echo.
echo Fetching the latest engagement data...
%PYEXE% fetch_engagement.py

echo.
echo Publishing to the web (only if Netlify is set up)...
%PYEXE% publish.py

echo.
echo Opening the dashboard...
start "" "engagement-dashboard.html"

echo.
echo Done. You can close this window.
pause
