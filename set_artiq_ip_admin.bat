@echo off
chcp 65001 >nul
echo This script sets the Ethernet adapter to 192.168.1.100/24.
echo Please run it as Administrator.
echo.

netsh interface ip set address name="以太网" static 192.168.1.100 255.255.255.0

if %errorlevel% neq 0 (
    echo.
    echo Failed. Right-click this file and choose "Run as administrator".
    pause
    exit /b %errorlevel%
)

echo.
echo Done. ARTIQ core 192.168.1.75 should now be reachable if the cable/core are OK.
pause
