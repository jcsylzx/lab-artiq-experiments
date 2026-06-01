@echo off
chcp 65001 >nul
setlocal

set "ARTIQ_BIN=E:\msys64\clang64\bin"
set "ARTIQ_HOME=D:\0核钟\任务\artiq_master"
set "BRIDGE=%~dp0artiq_repository\ttl_dataset_bridge.py"

if not exist "%BRIDGE%" (
    echo TTL bridge file not found: %BRIDGE%
    pause
    exit /b 1
)

cd /d "%ARTIQ_HOME%"
"%ARTIQ_BIN%\artiq_run.exe" --device-db device_db.py -c TTLDatasetBridge "%BRIDGE%" ttl_channel="'ttl0'" edge="'rising'" gate_time=0.1 update_period=0.1 max_samples=0
