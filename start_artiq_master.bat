@echo off
chcp 65001 >nul
setlocal

set "ARTIQ_BIN=E:\msys64\clang64\bin"
set "ARTIQ_HOME=D:\0核钟\任务\artiq_master"

cd /d "%ARTIQ_HOME%"
"%ARTIQ_BIN%\artiq_master.exe" -r repository --device-db device_db.py

if %errorlevel% neq 0 (
    echo.
    echo artiq_master exited with error code %errorlevel%.
    pause
)
