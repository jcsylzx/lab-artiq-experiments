@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

set "GUI_EXTRA_PYTHONPATH=%GUI_EXTRA_PYTHONPATH%"
cd /d "%PACKAGE_ROOT%"
if errorlevel 1 (
    pause
    exit /b 1
)
"%ARTIQ_BIN%\python.exe" "%PACKAGE_ROOT%\run_artiq_gui.py"
pause
