@echo off
setlocal DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PACKAGE_ROOT=%%~fI"

if exist "%PACKAGE_ROOT%\portable_config.bat" (
    call "%PACKAGE_ROOT%\portable_config.bat"
) else if exist "%PACKAGE_ROOT%\portable_config.example.bat" (
    call "%PACKAGE_ROOT%\portable_config.example.bat"
) else (
    echo Missing portable_config.example.bat
    exit /b 1
)

if not defined ARTIQ_BIN (
    for %%P in (
        "E:\msys64\clang64\bin"
        "C:\msys64\clang64\bin"
        "D:\msys64\clang64\bin"
        "E:\msys64\mingw64\bin"
        "C:\msys64\mingw64\bin"
        "D:\msys64\mingw64\bin"
    ) do (
        if exist "%%~P\artiq_run.exe" set "ARTIQ_BIN=%%~P"
    )
)

if not defined ARTIQ_BIN (
    for %%A in (artiq_run.exe) do set "ARTIQ_RUN_FOUND=%%~$PATH:A"
    if defined ARTIQ_RUN_FOUND for %%I in ("%ARTIQ_RUN_FOUND%") do set "ARTIQ_BIN=%%~dpI"
)

if not defined ARTIQ_BIN (
    echo Could not find ARTIQ tools. Edit portable_config.bat and set ARTIQ_BIN.
    exit /b 1
)

if not exist "%ARTIQ_BIN%\python.exe" (
    echo Could not find "%ARTIQ_BIN%\python.exe".
    exit /b 1
)

if not exist "%ARTIQ_BIN%\artiq_run.exe" (
    echo Could not find "%ARTIQ_BIN%\artiq_run.exe".
    exit /b 1
)

if not defined ARTIQ_HOME (
    echo ARTIQ_HOME is empty. Edit portable_config.bat.
    exit /b 1
)

set "MSYS_QT_PLUGIN_PATH="
set "MSYS_QT_PLATFORM_PATH="
set "PYQT_QT_BIN_PATH="
set "PYQT_QT_PLUGIN_PATH="
set "PYQT_QT_PLATFORM_PATH="
set "MSYS_USR_BIN_PATH="
for %%I in ("%ARTIQ_BIN%\..\..\usr\bin") do (
    if exist "%%~fI\msys-2.0.dll" set "MSYS_USR_BIN_PATH=%%~fI"
)
for %%I in ("%ARTIQ_BIN%\..\share\qt5\plugins") do (
    if exist "%%~fI\platforms\qwindows.dll" (
        set "MSYS_QT_PLUGIN_PATH=%%~fI"
        set "MSYS_QT_PLATFORM_PATH=%%~fI\platforms"
    )
)
for /f "usebackq delims=" %%I in (`"%ARTIQ_BIN%\python.exe" -c "from pathlib import Path; import PyQt5; root=Path(PyQt5.__file__).resolve().parent; qt=root/'Qt5'; bin=qt/'bin'; plugins=qt/'plugins'; print(bin if (bin/'Qt5Core.dll').exists() else ''); print(plugins if (plugins/'platforms'/'qwindows.dll').exists() else '')" 2^>nul`) do (
    if not defined PYQT_QT_BIN_PATH (
        if not "%%~I"=="" set "PYQT_QT_BIN_PATH=%%~I"
    ) else if not defined PYQT_QT_PLUGIN_PATH (
        if not "%%~I"=="" (
            set "PYQT_QT_PLUGIN_PATH=%%~I"
            set "PYQT_QT_PLATFORM_PATH=%%~I\platforms"
        )
    )
)

endlocal & (
    set "PACKAGE_ROOT=%PACKAGE_ROOT%"
    set "ARTIQ_BIN=%ARTIQ_BIN%"
    if not "%PYQT_QT_BIN_PATH%"=="" (
        if not "%MSYS_USR_BIN_PATH%"=="" (
            set "PATH=%ARTIQ_BIN%;%PYQT_QT_BIN_PATH%;%MSYS_USR_BIN_PATH%;%PATH%"
        ) else (
            set "PATH=%ARTIQ_BIN%;%PYQT_QT_BIN_PATH%;%PATH%"
        )
    ) else (
        if not "%MSYS_USR_BIN_PATH%"=="" (
            set "PATH=%ARTIQ_BIN%;%MSYS_USR_BIN_PATH%;%PATH%"
        ) else (
            set "PATH=%ARTIQ_BIN%;%PATH%"
        )
    )
    if not "%PYQT_QT_PLUGIN_PATH%"=="" (
        set "QT_PLUGIN_PATH=%PYQT_QT_PLUGIN_PATH%"
    ) else if not "%MSYS_QT_PLUGIN_PATH%"=="" (
        set "QT_PLUGIN_PATH=%MSYS_QT_PLUGIN_PATH%"
    )
    if not "%PYQT_QT_PLATFORM_PATH%"=="" (
        set "QT_QPA_PLATFORM_PLUGIN_PATH=%PYQT_QT_PLATFORM_PATH%"
    ) else if not "%MSYS_QT_PLATFORM_PATH%"=="" (
        set "QT_QPA_PLATFORM_PLUGIN_PATH=%MSYS_QT_PLATFORM_PATH%"
    )
    set "ARTIQ_HOME=%ARTIQ_HOME%"
    set "ARTIQ_CORE_ADDR=%ARTIQ_CORE_ADDR%"
    set "ETHERNET_NAME=%ETHERNET_NAME%"
    set "PC_STATIC_IP=%PC_STATIC_IP%"
    set "PC_STATIC_MASK=%PC_STATIC_MASK%"
    set "STAGE_PORT=%STAGE_PORT%"
    set "ARTIQ_MASTER_HOST=%ARTIQ_MASTER_HOST%"
    set "ARTIQ_MASTER_PORT=%ARTIQ_MASTER_PORT%"
    set "TTL_CHANNEL=%TTL_CHANNEL%"
    set "TTL_EDGE=%TTL_EDGE%"
    set "TTL_GATE_TIME=%TTL_GATE_TIME%"
    set "TTL_GATE_SUBDIVISIONS=%TTL_GATE_SUBDIVISIONS%"
    set "GUI_EXTRA_PYTHONPATH=%GUI_EXTRA_PYTHONPATH%"
)
