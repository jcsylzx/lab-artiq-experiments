r"""Small ARTIQ connectivity and TTL dataset debug helper.

Typical use after the Ethernet interface is on the same subnet as the core:

    python artiq_ttl_debug.py --core 192.168.1.75

To watch the datasets published by ttl_signal_monitor.py:

    python artiq_ttl_debug.py --skip-core --watch --seconds 10
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from typing import Iterable, Optional


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_DATASETS = (
    "pulse_latest",
    "counts",
    "ttl_monitor.count_rate",
    "ttl_monitor.sample",
    "ttl_monitor.timestamp",
    "ttl_monitor.status",
    "ttl_monitor.gate_time",
    "ttl_monitor.ttl_channel",
    "ttl_monitor.edge",
)


def find_exe(name: str) -> Optional[str]:
    return shutil.which(name) or shutil.which(name + ".exe")


def check_tcp(host: str, port: int, timeout: float = 1.5) -> tuple[bool, str]:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        return True, "open"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            sock.close()
        except Exception:
            pass


def run_cmd(args: list[str], timeout: float = 5.0) -> tuple[int, str]:
    proc = None
    try:
        proc = subprocess.Popen(
            args,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + timeout
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                output, _ = proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                output = ""
            return 124, f"timeout after {timeout:.1f}s\n{output.strip()}"
        output, _ = proc.communicate()
        return proc.returncode, output.strip()
    except OSError as exc:
        if proc is not None and proc.poll() is None:
            proc.kill()
        return 127, str(exc)


class DatasetReader:
    def __init__(self, host: str, port: int, target: str):
        self.host = host
        self.port = int(port)
        self.target = target
        self.client = None
        self.rpc_tool = find_exe("sipyco_rpctool")

    def connect(self) -> bool:
        try:
            from sipyco.pc_rpc import Client

            self.client = Client(self.host, self.port, self.target)
            return True
        except Exception as exc:
            print(f"[WARN] sipyco Client unavailable: {exc}")
            if self.rpc_tool:
                print(f"[INFO] Falling back to {self.rpc_tool}")
                return True
            return False

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close_rpc()
            except Exception:
                pass

    def get(self, name: str):
        if self.client is not None:
            return self.client.get(name)
        if not self.rpc_tool:
            raise RuntimeError("No sipyco client or sipyco_rpctool available")
        code, output = run_cmd(
            [
                self.rpc_tool,
                self.host,
                str(self.port),
                "call",
                "-t",
                self.target,
                "get",
                name,
            ],
            timeout=2.0,
        )
        if code != 0:
            raise RuntimeError(output)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""


def check_core(core: str) -> bool:
    print(f"[INFO] Checking ARTIQ core TCP ports at {core} ...")
    ports = (1380, 1381, 1382, 1383)
    results = []
    for port in ports:
        ok, detail = check_tcp(core, port)
        results.append(ok)
        print(f"  {port}: {detail}")

    if any(results):
        print("[OK] ARTIQ core TCP service is reachable")
        return True
    print("[FAIL] ARTIQ core TCP service is not reachable")
    return False


def show_datasets(master: str, port: int, target: str) -> bool:
    print(f"[INFO] Checking dataset RPC at {master}:{port}/{target} ...")
    ok, detail = check_tcp(master, port)
    if not ok:
        print(f"[FAIL] ARTIQ master dataset RPC port is not reachable: {detail}")
        return False
    reader = DatasetReader(master, port, target)
    if not reader.connect():
        print("[FAIL] ARTIQ master dataset RPC did not respond")
        return False

    print("[OK] ARTIQ master dataset RPC responded")
    found = False
    try:
        for name in DEFAULT_DATASETS:
            try:
                print(f"  {name}={reader.get(name)}")
                found = True
            except Exception:
                pass
    finally:
        reader.close()
    if not found:
        print("  (no TTL monitor datasets yet)")
    return True


def watch_datasets(
    host: str,
    port: int,
    target: str,
    datasets: Iterable[str],
    seconds: float,
    interval: float,
) -> None:
    reader = DatasetReader(host, port, target)
    if not reader.connect():
        print("[FAIL] Could not connect to dataset RPC")
        return

    print(f"[INFO] Watching datasets on {host}:{port}/{target}")
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            parts = []
            for name in datasets:
                try:
                    parts.append(f"{name}={reader.get(name)}")
                except Exception as exc:
                    parts.append(f"{name}=<missing: {exc}>")
            print(" | ".join(parts))
            time.sleep(interval)
    finally:
        reader.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default="192.168.1.75")
    parser.add_argument("--master", default="::1")
    parser.add_argument("--port", type=int, default=3251)
    parser.add_argument("--target", default="dataset_db")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--skip-core",
        action="store_true",
        help="do not probe core TCP ports; use this while a kernel is running",
    )
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--dataset", action="append", dest="datasets")
    args = parser.parse_args(argv)

    core_ok = True if args.skip_core else check_core(args.core)
    master_ok = show_datasets(args.master, args.port, args.target)

    if args.watch:
        datasets = tuple(args.datasets or DEFAULT_DATASETS)
        watch_datasets(
            args.master,
            args.port,
            args.target,
            datasets,
            args.seconds,
            args.interval,
        )

    return 0 if core_ok and master_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
