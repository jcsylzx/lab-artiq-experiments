@echo off
chcp 65001 >nul
echo ========================================
echo 多通道位移台 + ARTIQ 控制系统
echo ========================================
echo.

python main_gui.py

if %errorlevel% neq 0 (
    echo.
    echo 程序异常退出，错误码: %errorlevel%
    pause
)
