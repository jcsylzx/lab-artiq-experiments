[CmdletBinding()]
param(
    [string]$PackageRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Continue"
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $PackageRoot "logs"
$workDir = Join-Path $logDir ("diagnostics_" + $stamp)
$zipPath = Join-Path $logDir ("diagnostics_" + $stamp + ".zip")
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

function Capture-Text([string]$FileName, [scriptblock]$Action) {
    try {
        & $Action 2>&1 | Out-File -LiteralPath (Join-Path $workDir $FileName) -Encoding UTF8
    }
    catch {
        ("FAILED: " + $_.Exception.Message) | Out-File -LiteralPath (Join-Path $workDir $FileName) -Encoding UTF8
    }
}

function Find-MsysRoot {
    foreach ($root in @("C:\msys64", "D:\msys64", "E:\msys64")) {
        if (Test-Path -LiteralPath (Join-Path $root "usr\bin\pacman.exe")) {
            return $root
        }
    }
    return $null
}

Capture-Text "summary.txt" {
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    "PackageRoot: $PackageRoot"
    "ComputerName: $env:COMPUTERNAME"
    "UserName: $env:USERNAME"
    "PowerShell: $($PSVersionTable.PSVersion)"
    "OS: $((Get-CimInstance Win32_OperatingSystem).Caption)"
}

Capture-Text "ipconfig_all.txt" { ipconfig /all }
Capture-Text "serial_ports.txt" {
    Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.Name -match "\(COM[0-9]+\)" } |
        Select-Object Name, Status, DeviceID | Format-List
}
Capture-Text "processes.txt" {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -match "python|artiq|aqctl" } |
        Select-Object ProcessId, Name, CommandLine | Format-List
}

Capture-Text "tcp_checks.txt" {
    $config = Join-Path $PackageRoot "portable_config.bat"
    function ReadCfg([string]$Name, [string]$Default) {
        if (-not (Test-Path -LiteralPath $config)) { return $Default }
        $line = Get-Content -LiteralPath $config | Where-Object { $_ -match "^\s*set\s+`"$Name=(.*)`"\s*$" } | Select-Object -First 1
        if ($line -match "^\s*set\s+`"$Name=(.*)`"\s*$") { return $Matches[1] }
        return $Default
    }
    function TestTcp([string]$HostName, [int]$Port) {
        try { $addresses = [System.Net.Dns]::GetHostAddresses($HostName) }
        catch { return $_.Exception.Message }
        $lastError = ""
        foreach ($address in $addresses) {
            $client = New-Object System.Net.Sockets.TcpClient($address.AddressFamily)
            try {
                $async = $client.BeginConnect($address, $Port, $null, $null)
                if (-not $async.AsyncWaitHandle.WaitOne(1200, $false)) { continue }
                $client.EndConnect($async)
                return "open"
            }
            catch { $lastError = $_.Exception.Message }
            finally { $client.Close() }
        }
        if ($lastError) { return $lastError }
        return "timeout"
    }
    $core = ReadCfg "ARTIQ_CORE_ADDR" "192.168.1.75"
    $masterHost = ReadCfg "ARTIQ_MASTER_HOST" "::1"
    $masterPort = [int](ReadCfg "ARTIQ_MASTER_PORT" "3251")
    foreach ($port in 1380, 1381, 1382, 1383) {
        "core $core`:$port = $(TestTcp $core $port)"
    }
    "master dataset $masterHost`:$masterPort = $(TestTcp $masterHost $masterPort)"
}

$config = Join-Path $PackageRoot "portable_config.bat"
if (Test-Path -LiteralPath $config) {
    Copy-Item -LiteralPath $config -Destination (Join-Path $workDir "portable_config.bat") -Force
}
else {
    $exampleConfig = Join-Path $PackageRoot "portable_config.example.bat"
    if (Test-Path -LiteralPath $exampleConfig) {
        Copy-Item -LiteralPath $exampleConfig -Destination (Join-Path $workDir "portable_config.example.bat") -Force
    }
}

$msysRoot = Find-MsysRoot
if ($msysRoot) {
    $pacman = Join-Path $msysRoot "usr\bin\pacman.exe"
    $clangBin = Join-Path $msysRoot "clang64\bin"
    $python = Join-Path $clangBin "python.exe"
    Capture-Text "msys2_packages.txt" { & $pacman -Q }
    Capture-Text "pacman_config.txt" { Get-Content -LiteralPath (Join-Path $msysRoot "etc\pacman.conf") }
    Capture-Text "runtime_files.txt" {
        "MSYS2=$msysRoot"
        "Qt5Core exists: $(Test-Path -LiteralPath (Join-Path $clangBin 'Qt5Core.dll'))"
        "Python exists: $(Test-Path -LiteralPath $python)"
        "artiq_run exists: $(Test-Path -LiteralPath (Join-Path $clangBin 'artiq_run.exe'))"
    }
    if (Test-Path -LiteralPath $python) {
        $env:PATH = $clangBin + ";" + $env:PATH
        Capture-Text "python_import_test.txt" {
            & $python -c "import sys; print(sys.executable); print(sys.version); import artiq, sipyco, numpy, h5py, serial; print('ARTIQ dependencies OK'); import PyQt5.QtCore, PyQt5.QtWidgets, pyqtgraph; print('GUI dependencies OK'); print('Qt:', PyQt5.QtCore.QT_VERSION_STR)"
        }
        Capture-Text "artiq_version.txt" { & (Join-Path $clangBin "artiq_run.exe") --version }
    }
}
else {
    "No MSYS2 installation found at C:\msys64, D:\msys64, or E:\msys64." |
        Out-File -LiteralPath (Join-Path $workDir "msys2_not_found.txt") -Encoding UTF8
}

Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $zipPath } |
    Copy-Item -Destination $workDir -Force

Compress-Archive -LiteralPath $workDir -DestinationPath $zipPath -Force
Write-Host ""
Write-Host "Diagnostic bundle created:"
Write-Host $zipPath
