@echo off
rem Default configuration for the bundled full runtime package.

set "ARTIQ_BIN=%~dp0runtime\clang64\bin"
set "ARTIQ_HOME=%~dp0artiq_master"

set "ARTIQ_CORE_ADDR=192.168.1.75"
set "ETHERNET_NAME=Ethernet"
set "PC_STATIC_IP=192.168.1.100"
set "PC_STATIC_MASK=255.255.255.0"

set "STAGE_PORT=COM12"

set "ARTIQ_MASTER_HOST=::1"
set "ARTIQ_MASTER_PORT=3251"

set "TTL_CHANNEL=ttl0"
set "TTL_EDGE=rising"
set "TTL_GATE_TIME=0.01"
set "TTL_GATE_SUBDIVISIONS=1000"

set "GUI_EXTRA_PYTHONPATH="
