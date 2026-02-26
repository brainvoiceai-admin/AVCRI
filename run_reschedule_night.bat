@echo off
REM Batch script to run night reschedule algorithm (next day's treatments)
REM Schedule this at 8:00 PM daily via Windows Task Scheduler
REM Logs are written to: AVCRI\logs\reschedule_night_YYYY-MM-DD.log

cd /d "C:\Users\jaise\OneDrive\Desktop\git\AVCRI"

REM Create logs folder if it does not exist
if not exist "logs" mkdir logs

REM Log file name with today's date (YYYY-MM-DD) - uses PowerShell for reliable format
for /f "usebackq" %%d in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd'"`) do set LOGDATE=%%d
set LOGFILE=logs\reschedule_night_%LOGDATE%.log

REM Append run with timestamp and full output to log file
echo. >> "%LOGFILE%"
echo ========== RUN STARTED: %date% %time% ========== >> "%LOGFILE%"
echo. >> "%LOGFILE%"
python manage.py reschedule_night >> "%LOGFILE%" 2>&1
echo. >> "%LOGFILE%"
echo ========== RUN ENDED: %date% %time% ========== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM When run by Task Scheduler there is no console; check the log file to confirm run.
REM When run manually (double-click), window stays open briefly showing log path.
echo Log written to: %LOGFILE%
timeout /t 3 >nul
