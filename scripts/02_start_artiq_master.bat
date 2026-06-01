@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

cd /d "%ARTIQ_HOME%"
if errorlevel 1 (
    pause
    exit /b 1
)
if not exist "%PACKAGE_ROOT%\logs" mkdir "%PACKAGE_ROOT%\logs"
echo Checking for existing artiq_master processes on this computer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$self=$PID; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $self -and (($_.Name -eq 'artiq_master.exe') -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'artiq_master')) } | ForEach-Object { Write-Host ('Stopping old artiq_master PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
echo Logging to "%PACKAGE_ROOT%\logs\artiq_master.log"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { & '%ARTIQ_BIN%\artiq_master.exe' -r repository --device-db device_db.py 2>&1 | Tee-Object -FilePath '%PACKAGE_ROOT%\logs\artiq_master.log' -Append }"
pause
