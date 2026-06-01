@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

cd /d "%PACKAGE_ROOT%"
if errorlevel 1 (
    pause
    exit /b 1
)
"%ARTIQ_BIN%\python.exe" "%PACKAGE_ROOT%\artiq_ttl_debug.py" --skip-core --master %ARTIQ_MASTER_HOST% --port %ARTIQ_MASTER_PORT% --watch --seconds 30 --interval 1
pause
