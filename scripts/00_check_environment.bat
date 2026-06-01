@echo off
chcp 65001 >nul
call "%~dp0common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo PACKAGE_ROOT=%PACKAGE_ROOT%
echo ARTIQ_BIN=%ARTIQ_BIN%
echo ARTIQ_HOME=%ARTIQ_HOME%
echo ARTIQ_CORE_ADDR=%ARTIQ_CORE_ADDR%
echo ARTIQ_MASTER=%ARTIQ_MASTER_HOST%:%ARTIQ_MASTER_PORT%
echo STAGE_PORT=%STAGE_PORT%
echo TTL=%TTL_CHANNEL% edge=%TTL_EDGE% gate=%TTL_GATE_TIME%s
echo.

if defined GUI_EXTRA_PYTHONPATH (
    set "PYTHONPATH=%GUI_EXTRA_PYTHONPATH%;%PYTHONPATH%"
    echo GUI_EXTRA_PYTHONPATH=%GUI_EXTRA_PYTHONPATH%
    echo.
)

echo [1/5] Checking ARTIQ Python modules...
"%ARTIQ_BIN%\python.exe" -c "import artiq, sipyco, numpy; print('OK: artiq/sipyco/numpy')" 2>nul
if errorlevel 1 (
    echo FAIL: ARTIQ Python cannot import artiq/sipyco/numpy.
    echo Check ARTIQ_BIN in portable_config.bat.
    echo.
)
"%ARTIQ_BIN%\artiq_run.exe" --version 2>nul
"%ARTIQ_BIN%\python.exe" -c "import artiq.language.core as c; print('NAC3 compile decorator:', hasattr(c, 'compile'))" 2>nul
echo Device-tested host version: ARTIQ v8.9009+6f600dd
echo If another ARTIQ version is shown, continue to hardware tests; a core
echo protocol/version mismatch means the core firmware and host ARTIQ differ.
echo.

echo [2/5] Checking GUI modules...
"%ARTIQ_BIN%\python.exe" -c "import PyQt5.QtCore, PyQt5.QtWidgets, pyqtgraph; print('OK: PyQt5/pyqtgraph')" 2>nul
if errorlevel 1 (
    echo FAIL: GUI modules are missing.
    echo.
    echo --- GUI import diagnostics ---
    echo ARTIQ_BIN=%ARTIQ_BIN%
    echo This script prepends ARTIQ_BIN to PATH before running Python.
    if exist "%ARTIQ_BIN%\Qt5Core.dll" (
        echo OK: Found "%ARTIQ_BIN%\Qt5Core.dll"
    ) else (
        echo FAIL: Missing "%ARTIQ_BIN%\Qt5Core.dll"
    )
    if defined QT_QPA_PLATFORM_PLUGIN_PATH (
        echo QT_QPA_PLATFORM_PLUGIN_PATH=%QT_QPA_PLATFORM_PLUGIN_PATH%
    ) else (
        echo QT_QPA_PLATFORM_PLUGIN_PATH is not set
    )
    if exist "%QT_QPA_PLATFORM_PLUGIN_PATH%\qwindows.dll" (
        echo OK: Found qwindows.dll
    ) else (
        echo WARN: qwindows.dll not found at QT_QPA_PLATFORM_PLUGIN_PATH
    )
    echo.
    echo Real Python error:
    "%ARTIQ_BIN%\python.exe" -c "import sys, os; print(sys.executable); print(sys.version); import PyQt5; print('PyQt5 path:', PyQt5.__file__); import PyQt5.QtCore; print('QtCore OK'); import PyQt5.QtWidgets; print('QtWidgets OK'); import pyqtgraph; print('pyqtgraph OK')"
    echo --- end diagnostics ---
    echo.
    echo If Qt5Core.dll is missing, install the MSYS2 Qt/PyQt packages for the same environment.
    echo You can run scripts\07_fix_gui_deps_msys2.bat for this.
    echo If Qt5Core.dll exists but import still fails, another Qt dependency DLL is missing or mixed.
    echo In that case, reinstall PyQt5/pyqtgraph inside this ARTIQ/MSYS2 environment.
    echo.
)

echo [3/5] Checking serial module...
"%ARTIQ_BIN%\python.exe" -c "import serial; print('OK: pyserial')" 2>nul
if errorlevel 1 (
    echo WARN: pyserial is missing.
    echo Stage control will fail unless pyserial is installed or GUI_EXTRA_PYTHONPATH is set.
    echo ARTIQ-only TTL testing can continue without the stage.
    echo.
)

echo [4/5] Checking ARTIQ master directory...
if exist "%ARTIQ_HOME%\device_db.py" (
    echo OK: Found "%ARTIQ_HOME%\device_db.py"
) else (
    echo FAIL: Missing "%ARTIQ_HOME%\device_db.py"
)

if exist "%ARTIQ_HOME%\repository" (
    echo OK: Found "%ARTIQ_HOME%\repository"
) else (
    echo WARN: Missing "%ARTIQ_HOME%\repository"
)

echo [5/5] Checking packaged files...
if exist "%PACKAGE_ROOT%\main_gui.py" (
    echo OK: Found main_gui.py
) else (
    echo FAIL: Missing "%PACKAGE_ROOT%\main_gui.py"
)
if exist "%PACKAGE_ROOT%\artiq_repository\ttl_dataset_bridge.py" (
    echo OK: Found ttl_dataset_bridge.py
) else (
    echo FAIL: Missing "%PACKAGE_ROOT%\artiq_repository\ttl_dataset_bridge.py"
)

echo.
echo Environment check finished. FAIL lines must be fixed; WARN lines may be acceptable for ARTIQ-only testing.
pause
