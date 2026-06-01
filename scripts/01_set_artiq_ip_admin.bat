@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo This sets %ETHERNET_NAME% to %PC_STATIC_IP%/%PC_STATIC_MASK%.
echo Run this file as Administrator if Windows rejects the command.
echo.
netsh interface ip set address name="%ETHERNET_NAME%" static %PC_STATIC_IP% %PC_STATIC_MASK%
pause
