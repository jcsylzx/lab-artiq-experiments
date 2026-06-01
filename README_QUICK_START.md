# Quick Start for a New Computer

Prerequisite: install base MSYS2 and connect the computer to the Internet.

1. Run `scripts\00_FIRST_RUN_INSTALL_ALL.bat`.
   This installs the pinned device-compatible `ARTIQ v8.9009+6f600dd` plus
   GUI, serial, and data dependencies, and creates `portable_config.bat`.
2. Edit `portable_config.bat`, especially `ETHERNET_NAME` and `STAGE_PORT`.
3. Run `scripts\00_check_environment.bat`.
4. Run `scripts\01_set_artiq_ip_admin.bat` as Administrator when the ARTIQ
   core is directly connected by Ethernet.
5. Keep `scripts\02_start_artiq_master.bat` running.
6. Keep `scripts\03_start_ttl_bridge.bat` running.
7. Use `scripts\05_watch_ttl_dataset.bat` to verify TTL counts.
8. Run `scripts\04_run_gui_artiq.bat`.

If any step fails, run `scripts\09_export_diagnostics.bat` and provide the
generated `logs\diagnostics_*.zip`.

Full Chinese manual: `docs\使用说明书.md`.
