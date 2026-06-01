@echo off
chcp 65001 >nul
set "PACKAGE_ROOT=%~dp0.."

echo Checking ARTIQ runtime, core TCP ports, master dataset RPC, and recent logs...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_runtime_status.ps1" -PackageRoot "%PACKAGE_ROOT%"
echo.
pause
