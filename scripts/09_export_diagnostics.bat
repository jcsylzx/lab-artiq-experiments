@echo off
chcp 65001 >nul
set "PACKAGE_ROOT=%~dp0.."

echo Collecting installation logs and local environment diagnostics...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0export_diagnostics.ps1" -PackageRoot "%PACKAGE_ROOT%"
echo.
echo Send the generated diagnostics_*.zip file from the logs folder for analysis.
pause
