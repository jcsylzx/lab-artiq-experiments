@echo off
rem Copy this file to portable_config.bat and edit it for the target computer.

rem Folder that contains artiq_master.exe, artiq_run.exe, artiq_client.exe.
rem Leave empty to search PATH and common MSYS2 locations.
set "ARTIQ_BIN="

rem Folder that contains device_db.py and the repository/ directory.
rem The full installer package carries the verified hnl30 configuration here.
set "ARTIQ_HOME=%~dp0artiq_master"

rem ARTIQ core network settings.
set "ARTIQ_CORE_ADDR=192.168.1.75"
rem Network interface name. Examples: Ethernet, Ethernet 2.
rem On Chinese Windows this may be the Chinese name shown by:
rem   netsh interface ip show config
set "ETHERNET_NAME=Ethernet"
set "PC_STATIC_IP=192.168.1.100"
set "PC_STATIC_MASK=255.255.255.0"

rem GUI/stage defaults. Edit COM number for the target computer; use SIM without the stage.
set "STAGE_PORT=COM12"

rem ARTIQ master/dataset settings.
set "ARTIQ_MASTER_HOST=::1"
set "ARTIQ_MASTER_PORT=3251"

rem TTL bridge settings.
rem TTL_EDGE, TTL_GATE_TIME, and TTL_GATE_SUBDIVISIONS are software-adjustable.
rem The voltage trigger threshold of ttl0-ttl3 is fixed by TTL input hardware
rem or the external PMT discriminator/comparator, not by ARTIQ software.
set "TTL_CHANNEL=ttl0"
set "TTL_EDGE=rising"
set "TTL_GATE_TIME=0.01"
set "TTL_GATE_SUBDIVISIONS=1000"

rem Optional: add another Python site-packages directory for pure-Python deps
rem such as pyserial. Leave empty if the ARTIQ Python already imports serial.
set "GUI_EXTRA_PYTHONPATH="
