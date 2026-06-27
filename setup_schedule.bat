@echo off
REM ===========================================================
REM  One-time setup: schedule a daily background data refresh.
REM  Double-click this once. To change the time, edit the
REM  07:00 below and run it again.
REM ===========================================================
setlocal
set TASKNAME=GCC Engagement Dashboard Refresh
set SCRIPT=%~dp0refresh_quiet.bat
set REFRESHTIME=07:00

echo Registering a daily refresh at %REFRESHTIME% ...
echo.
schtasks /create /tn "%TASKNAME%" /tr "\"%SCRIPT%\"" /sc DAILY /st %REFRESHTIME% /f

if %ERRORLEVEL%==0 (
  echo.
  echo ============================================================
  echo  Success. Your dashboard data will refresh automatically
  echo  every day at %REFRESHTIME%, as long as the computer is on
  echo  and you are signed in.
  echo.
  echo  - To see it work now: open run_dashboard.bat any time.
  echo  - To change the time: edit REFRESHTIME above, run this again.
  echo  - To remove it: open Task Scheduler and delete the task
  echo    named "%TASKNAME%".
  echo ============================================================
) else (
  echo.
  echo Could not register the task automatically.
  echo Right-click this file, choose "Run as administrator",
  echo then run it again.
)

echo.
pause
endlocal
