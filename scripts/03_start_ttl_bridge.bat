@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

set "BRIDGE=%PACKAGE_ROOT%\artiq_repository\ttl_dataset_bridge.py"
if not exist "%BRIDGE%" (
    echo Missing "%BRIDGE%"
    pause
    exit /b 1
)

cd /d "%ARTIQ_HOME%"
if errorlevel 1 (
    pause
    exit /b 1
)
if not exist "%PACKAGE_ROOT%\logs" mkdir "%PACKAGE_ROOT%\logs"
echo Starting TTL bridge. Keep this window open while using the GUI.
echo Do not run another artiq_run/probe on the core at the same time.
echo Checking ARTIQ master dataset RPC at %ARTIQ_MASTER_HOST%:%ARTIQ_MASTER_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$hostName='%ARTIQ_MASTER_HOST%'; $port=[int]'%ARTIQ_MASTER_PORT%'; $ok=$false; try { $addresses=[System.Net.Dns]::GetHostAddresses($hostName); foreach($addr in $addresses){ $client=New-Object System.Net.Sockets.TcpClient($addr.AddressFamily); $async=$client.BeginConnect($addr,$port,$null,$null); if($async.AsyncWaitHandle.WaitOne(1200,$false)){ $client.EndConnect($async); $ok=$true; $client.Close(); break }; $client.Close() } } catch { Write-Host $_.Exception.Message }; if(-not $ok){ Write-Host 'ARTIQ master dataset RPC is not reachable. Start scripts\02_start_artiq_master.bat first and keep that window open.'; exit 1 }"
if errorlevel 1 (
    pause
    exit /b 1
)
echo Logging to "%PACKAGE_ROOT%\logs\ttl_bridge.log"
if not defined TTL_GATE_SUBDIVISIONS set "TTL_GATE_SUBDIVISIONS=1000"
echo Effective TTL settings: channel=%TTL_CHANNEL% edge=%TTL_EDGE% gate=%TTL_GATE_TIME%s gates_per_batch=%TTL_GATE_SUBDIVISIONS%
:restart_bridge
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { & '%ARTIQ_BIN%\artiq_run.exe' --device-db device_db.py -c TTLDatasetBridge '%BRIDGE%' ttl_channel=\"'%TTL_CHANNEL%'\" edge=\"'%TTL_EDGE%'\" gate_time=%TTL_GATE_TIME% gate_subdivisions=%TTL_GATE_SUBDIVISIONS% max_samples=0 master_host=\"'%ARTIQ_MASTER_HOST%'\" master_port=%ARTIQ_MASTER_PORT% 2>&1 | Tee-Object -FilePath '%PACKAGE_ROOT%\logs\ttl_bridge.log' -Append }"
echo TTL bridge exited with code %ERRORLEVEL%.
echo Restarting in 3 seconds. Close this window to stop.
timeout /t 3 /nobreak >nul
goto restart_bridge
pause
