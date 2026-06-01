[CmdletBinding()]
param(
    [string]$PackageRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Continue"
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$logDir = Join-Path $PackageRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "runtime_check_$stamp.log"

function Load-ConfigValue([string]$Name, [string]$Default) {
    $config = Join-Path $PackageRoot "portable_config.bat"
    if (-not (Test-Path -LiteralPath $config)) { return $Default }
    $line = Get-Content -LiteralPath $config | Where-Object { $_ -match "^\s*set\s+`"$Name=(.*)`"\s*$" } | Select-Object -First 1
    if ($line -match "^\s*set\s+`"$Name=(.*)`"\s*$") { return $Matches[1] }
    return $Default
}

function Test-Tcp([string]$HostName, [int]$Port, [int]$TimeoutMs = 1200) {
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses($HostName)
    }
    catch {
        return $_.Exception.Message
    }
    foreach ($address in $addresses) {
        $client = New-Object System.Net.Sockets.TcpClient($address.AddressFamily)
        try {
            $async = $client.BeginConnect($address, $Port, $null, $null)
            if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
                continue
            }
            $client.EndConnect($async)
            return "open"
        }
        catch {
            $lastError = $_.Exception.Message
        }
        finally {
            $client.Close()
        }
    }
    if ($lastError) {
        return $lastError
    }
    return "timeout"
}

Start-Transcript -LiteralPath $logPath -Force | Out-Null
try {
    $artiqBin = Load-ConfigValue "ARTIQ_BIN" "E:\msys64\clang64\bin"
    $artiqHome = Load-ConfigValue "ARTIQ_HOME" (Join-Path $PackageRoot "artiq_master")
    $core = Load-ConfigValue "ARTIQ_CORE_ADDR" "192.168.1.75"
    $masterHost = Load-ConfigValue "ARTIQ_MASTER_HOST" "::1"
    $masterPort = [int](Load-ConfigValue "ARTIQ_MASTER_PORT" "3251")
    $ttlChannel = Load-ConfigValue "TTL_CHANNEL" "ttl0"

    "PackageRoot=$PackageRoot"
    "ARTIQ_BIN=$artiqBin"
    "ARTIQ_HOME=$artiqHome"
    "ARTIQ_CORE_ADDR=$core"
    "ARTIQ_MASTER=$masterHost`:$masterPort"
    "TTL_CHANNEL=$ttlChannel"
    ""

    "Processes:"
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -match "python|artiq|aqctl" } |
        Select-Object ProcessId, Name, CommandLine | Format-List

    "TCP checks:"
    foreach ($port in 1380, 1381, 1382, 1383) {
        "core $core`:$port = $(Test-Tcp $core $port)"
    }
    "master dataset $masterHost`:$masterPort = $(Test-Tcp $masterHost $masterPort)"
    ""

    $python = Join-Path $artiqBin "python.exe"
    $artiqRun = Join-Path $artiqBin "artiq_run.exe"
    if (Test-Path -LiteralPath $artiqRun) {
        "ARTIQ version:"
        & $artiqRun --version
    }
    if (Test-Path -LiteralPath $python) {
        "Python import check:"
        & $python -c "import artiq, sipyco, numpy, h5py, serial; import PyQt5.QtCore, pyqtgraph; print('imports OK')"
        ""
        "Dataset check:"
        & $python (Join-Path $PackageRoot "artiq_ttl_debug.py") --skip-core --master $masterHost --port $masterPort
    }

    ""
    "Recent logs:"
    Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 12 Name, Length, LastWriteTime | Format-Table -AutoSize
}
finally {
    Stop-Transcript | Out-Null
    Write-Host ""
    Write-Host "Runtime check log:"
    Write-Host $logPath
}
