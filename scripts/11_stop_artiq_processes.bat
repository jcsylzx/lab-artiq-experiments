@echo off
chcp 65001 >nul
echo Stopping existing ARTIQ master/run processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(artiq_.*|python)\\.exe$' -and $_.CommandLine -match 'artiq_master|artiq_run|ttl_dataset_bridge|ttl_input_probe|ttl_level_probe|ttl_signal_monitor' } | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId + ' ' + $_.Name); Stop-Process -Id $_.ProcessId -Force }"
echo Done.
pause
