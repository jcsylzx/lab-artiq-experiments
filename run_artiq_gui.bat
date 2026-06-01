@echo off
chcp 65001 >nul
setlocal

set "ARTIQ_PYTHON=E:\msys64\clang64\bin\python.exe"

if not exist "%ARTIQ_PYTHON%" (
    echo ARTIQ Python not found: %ARTIQ_PYTHON%
    pause
    exit /b 1
)

"%ARTIQ_PYTHON%" "%~dp0run_artiq_gui.py"

if %errorlevel% neq 0 (
    echo.
    echo GUI exited with error code %errorlevel%.
    pause
)
