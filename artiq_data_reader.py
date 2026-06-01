"""
ARTIQ 脉冲信号数据读取接口。

支持三种模式：
1. simulated - 位置相关模拟数据，便于无硬件调试 GUI
2. sipyco - 通过 ARTIQ master dataset RPC 读取实时 dataset
3. hdf5 - 从最近的 ARTIQ HDF5 结果文件读取

当前 artiq_master/repository 中已有的 dataset 命名包括：
    scan.intensity
    scan.progress
    scan2d.image
    scan2d.progress

如果 dataset_name 设置为 "auto"，读取器会按候选列表依次尝试，优先读取
pulse_latest/counts 一类实时标量，其次兼容上面的扫描 dataset。
"""

import glob
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np


DEFAULT_DATASETS = (
    "ttl_monitor.count_rate",
    "pulse_latest",
    "counts",
    "count",
    "ttl_monitor.count_history",
    "latest_counts",
    "scan.latest",
    "scan.intensity",
    "scan2d.image",
)

PROGRESS_DATASETS = {
    "scan.intensity": "scan.progress",
    "scan2d.image": "scan2d.progress",
}

DATASET_RPC_TARGETS = ("dataset_db", "master_dataset_db")


class ARTIQDataReader:
    """ARTIQ 数据读取器。"""

    def __init__(
        self,
        mode: str = "simulated",
        master_host: str = "::1",
        master_port: int = 3251,
        dataset_name: str = "auto",
        target_name: str = "dataset_db",
        results_dir: Optional[str] = None,
        candidate_datasets: Iterable[str] = DEFAULT_DATASETS,
    ):
        self.mode = mode
        self.master_host = master_host
        self.master_port = int(master_port)
        self.dataset_name = dataset_name.strip() or "auto"
        self.target_name = target_name
        self.results_dir = results_dir
        self.candidate_datasets = tuple(candidate_datasets)
        self._sim_time_start = time.time()
        self._rpc_client = None
        self.last_error = ""
        self.last_warning = ""
        self.last_dataset = ""
        self.last_monitor_sample = None
        self.last_monitor_change_time = 0.0
        self.last_sample_id = None
        self.last_sample_timestamp = 0.0
        self.last_status = ""
        self.last_is_new_sample = False
        self.stale_after_seconds = 3.0
        self._last_error_print = 0.0
        self.last_unit = "kHz"

    # ----------------------------------------------------------------
    # 配置与连接
    # ----------------------------------------------------------------
    def configure(
        self,
        *,
        mode: Optional[str] = None,
        master_host: Optional[str] = None,
        master_port: Optional[int] = None,
        dataset_name: Optional[str] = None,
        results_dir: Optional[str] = None,
    ):
        """更新配置；如果连接参数变化，会关闭现有 RPC 连接。"""
        reconnect = False
        if mode is not None and mode != self.mode:
            self.mode = mode
            reconnect = True
        if master_host is not None and master_host != self.master_host:
            self.master_host = master_host
            reconnect = True
        if master_port is not None and int(master_port) != self.master_port:
            self.master_port = int(master_port)
            reconnect = True
        if dataset_name is not None:
            self.dataset_name = dataset_name.strip() or "auto"
        if results_dir is not None:
            self.results_dir = results_dir
        if reconnect:
            self.disconnect()

    def connect(self) -> bool:
        """连接到 ARTIQ master；非 sipyco 模式直接视为可用。"""
        self.last_error = ""
        if self.mode != "sipyco":
            return True
        if self._rpc_client is not None:
            return True
        try:
            from sipyco.pc_rpc import Client

            targets = [self.target_name]
            targets.extend(t for t in DATASET_RPC_TARGETS if t not in targets)
            errors = []
            for target in targets:
                try:
                    self._rpc_client = Client(
                        self.master_host,
                        self.master_port,
                        target,
                    )
                    self.target_name = target
                    return True
                except Exception as exc:
                    self._rpc_client = None
                    errors.append(f"{target}: {exc}")
            self._record_error(
                "连接 ARTIQ dataset RPC 失败: " + " | ".join(errors)
            )
            return False
        except ModuleNotFoundError as exc:
            self._rpc_client = None
            if exc.name == "sipyco":
                self._record_error(
                    "当前 Python 环境缺少 sipyco；请用 run_artiq_gui.bat "
                    "启动 GUI，或在当前环境安装 sipyco"
                )
            else:
                self._record_error(f"连接 ARTIQ master 失败: {exc}")
            return False
        except Exception as exc:
            self._rpc_client = None
            self._record_error(f"连接 ARTIQ master 失败: {exc}")
            return False

    def disconnect(self):
        """断开 RPC 连接。"""
        if self._rpc_client is not None:
            try:
                self._rpc_client.close_rpc()
            except Exception:
                pass
            self._rpc_client = None

    def set_ttl_config(
        self,
        *,
        gate_time: Optional[float] = None,
        gate_subdivisions: Optional[int] = None,
    ) -> bool:
        """Write runtime TTL bridge settings into ARTIQ datasets."""
        if self.mode != "sipyco":
            self.last_error = "TTL参数只能写入 sipyco/ARTIQ 数据源"
            return False
        if not self.connect():
            return False
        try:
            if gate_time is not None:
                self._rpc_client.set(
                    "ttl_monitor.config.gate_time",
                    float(gate_time),
                    persist=False,
                )
            if gate_subdivisions is not None:
                self._rpc_client.set(
                    "ttl_monitor.config.gate_subdivisions",
                    int(gate_subdivisions),
                    persist=False,
                )
            self.last_error = ""
            return True
        except Exception as exc:
            self._record_error(f"写入TTL参数失败: {exc}")
            return False

    # ----------------------------------------------------------------
    # 数据读取
    # ----------------------------------------------------------------
    def read_intensity(self, positions=None) -> Optional[float]:
        """
        读取当前脉冲信号强度。

        positions 可选，用于模拟模式生成位置相关信号。
        """
        if self.mode == "simulated":
            self.last_dataset = "simulated"
            self.last_warning = ""
            self.last_status = "running"
            self.last_is_new_sample = True
            self.last_sample_timestamp = time.time()
            self.last_sample_id = (
                1 if self.last_sample_id is None else self.last_sample_id + 1
            )
            return self._read_simulated(positions)
        if self.mode == "sipyco":
            return self._read_from_sipyco()
        if self.mode == "hdf5":
            return self._read_from_hdf5()
        self._record_error(f"未知 ARTIQ 数据模式: {self.mode}")
        return None

    def read_all_channels(self) -> Dict[int, Optional[float]]:
        """
        读取多通道最新计数，dataset 命名约定为 ch0_latest...ch3_latest。
        """
        if self.mode == "simulated":
            return {i: self._read_simulated(None) for i in range(4)}
        if self.mode != "sipyco" or not self.connect():
            return {i: None for i in range(4)}

        result = {}
        for ch in range(4):
            try:
                result[ch] = self._extract_numeric(
                    self._rpc_client.get(f"ch{ch}_latest")
                )
            except Exception:
                result[ch] = None
        return result

    def _read_from_sipyco(self) -> Optional[float]:
        if not self.connect():
            return None

        if self.dataset_name.lower() == "auto":
            for name in self.candidate_datasets:
                value = self._read_named_dataset(name, quiet=True)
                if value is not None:
                    self.last_dataset = name
                    self.last_error = ""
                    self._update_ttl_monitor_status()
                    return self._to_khz(name, value)
            self._record_error("未找到可用的 ARTIQ dataset")
            return None

        value = self._read_named_dataset(self.dataset_name, quiet=False)
        if value is not None:
            self.last_dataset = self.dataset_name
            self.last_error = ""
            self._update_ttl_monitor_status()
            return self._to_khz(self.dataset_name, value)
        return None

    def _update_ttl_monitor_status(self):
        """Detect a stopped TTL bridge by watching ttl_monitor.sample."""
        self.last_warning = ""
        self.last_is_new_sample = False
        if self.mode != "sipyco" or self._rpc_client is None:
            return
        try:
            sample = int(self._rpc_client.get("ttl_monitor.sample"))
        except Exception:
            return
        try:
            self.last_status = str(self._rpc_client.get("ttl_monitor.status"))
        except Exception:
            self.last_status = ""
        try:
            self.last_sample_timestamp = float(
                self._rpc_client.get("ttl_monitor.timestamp"))
        except Exception:
            self.last_sample_timestamp = 0.0

        now = time.time()
        if sample != self.last_monitor_sample:
            self.last_is_new_sample = True
            self.last_sample_id = sample
            self.last_monitor_sample = sample
            self.last_monitor_change_time = now
            return

        if self.last_monitor_change_time <= 0.0:
            self.last_monitor_change_time = now
            return

        age = now - self.last_monitor_change_time
        if age >= self.stale_after_seconds:
            self.last_warning = (
                f"TTL桥接可能已停止：sample={sample} 已 {age:.1f}s 未更新"
            )

    def _read_named_dataset(self, name: str, *, quiet: bool) -> Optional[float]:
        try:
            data = self._rpc_client.get(name)
            progress = None
            progress_name = PROGRESS_DATASETS.get(name)
            if progress_name:
                try:
                    progress = self._rpc_client.get(progress_name)
                except Exception:
                    progress = None
            return self._extract_numeric(data, progress=progress)
        except Exception as exc:
            if not quiet:
                self._record_error(f"读取 dataset '{name}' 失败: {exc}")
            return None

    def _to_khz(self, name: str, value: float) -> float:
        """Convert ARTIQ TTL datasets to kHz for GUI display and plots."""
        dataset = (name or "").lower()
        if dataset in ("ttl_monitor.count_rate", "count_rate"):
            return float(value) / 1000.0

        count_datasets = {
            "pulse_latest",
            "counts",
            "count",
            "latest_counts",
            "ttl_monitor.count_history",
        }
        if dataset in count_datasets:
            gate_time = self._read_gate_time(default=1.0)
            if gate_time > 0:
                return float(value) / gate_time / 1000.0
        return float(value)

    def _read_gate_time(self, default: float = 1.0) -> float:
        if self.mode != "sipyco" or self._rpc_client is None:
            return default
        try:
            gate_time = float(self._rpc_client.get("ttl_monitor.gate_time"))
            return gate_time if gate_time > 0 else default
        except Exception:
            return default

    def _read_from_hdf5(self) -> Optional[float]:
        try:
            import h5py

            files = self._find_hdf5_files()
            if not files:
                self._record_error("未找到 HDF5 结果文件")
                return None

            with h5py.File(files[-1], "r") as handle:
                for name in self._hdf5_dataset_candidates():
                    data = self._get_hdf5_dataset(handle, name)
                    if data is not None:
                        self.last_dataset = name
                        return self._extract_numeric(data)
            self._record_error(f"HDF5 中未找到 dataset: {self.dataset_name}")
            return None
        except Exception as exc:
            self._record_error(f"读取 HDF5 失败: {exc}")
            return None

    def _find_hdf5_files(self):
        roots = []
        if self.results_dir:
            roots.append(Path(self.results_dir))

        here = Path(__file__).resolve().parent
        roots.append(here / "results")
        roots.append(here.parent.parent / "artiq_master" / "results")

        files = []
        for root in roots:
            if root.exists():
                files.extend(glob.glob(str(root / "**" / "*.h5"), recursive=True))
        return sorted(set(files), key=os.path.getmtime)

    def _hdf5_dataset_candidates(self):
        if self.dataset_name.lower() != "auto":
            return (self.dataset_name,)
        return self.candidate_datasets

    @staticmethod
    def _get_hdf5_dataset(handle, name: str):
        candidates = [
            name,
            f"datasets/{name}",
            f"datasets/{name.replace('.', '/')}",
        ]
        for candidate in candidates:
            if candidate in handle:
                return handle[candidate][()]
        return None

    # ----------------------------------------------------------------
    # 数值提取与模拟数据
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_numeric(value: Any, progress: Any = None) -> Optional[float]:
        """把标量、数组或简单 dict 转成一个最新强度值。"""
        if value is None:
            return None

        if isinstance(value, dict):
            for key in ("latest", "pulse_latest", "counts", "count", "intensity"):
                if key in value:
                    return ARTIQDataReader._extract_numeric(value[key], progress)
            return None

        try:
            arr = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        if arr.shape == ():
            scalar = float(arr)
            return scalar if np.isfinite(scalar) else None

        flat = arr.ravel()
        if flat.size == 0:
            return None

        idx = None
        if progress is not None:
            try:
                idx = int(progress) - 1
            except (TypeError, ValueError):
                idx = None
        if idx is not None and idx >= 0:
            idx = min(idx, flat.size - 1)
            val = float(flat[idx])
            return val if np.isfinite(val) else None

        finite = flat[np.isfinite(flat)]
        if finite.size == 0:
            return None
        return float(finite[-1])

    def _read_simulated(self, positions=None) -> float:
        """生成位置相关模拟数据，便于测试 1D/2D 绘图链路。"""
        noise = np.random.normal(0, 3)

        if positions is not None and len(positions) >= 2:
            x = positions[0] if positions[0] is not None else 0.0
            y = positions[1] if positions[1] is not None else 0.0
            g1 = 200.0 * np.exp(-((x - 0.3) ** 2 + (y + 0.2) ** 2) / 0.15)
            g2 = 120.0 * np.exp(-((x + 0.5) ** 2 + (y - 0.4) ** 2) / 0.08)
            band = 50.0 * np.exp(-((x + y) ** 2) / 0.05)
            return float(50.0 + g1 + g2 + band + noise)

        t = time.time() - self._sim_time_start
        return float(100.0 + 50.0 * np.sin(0.5 * t) + noise)

    def _record_error(self, message: str):
        self.last_error = message
        now = time.time()
        if now - self._last_error_print > 2.0:
            print(message)
            self._last_error_print = now


if __name__ == "__main__":
    print("=== 测试模拟模式 ===")
    reader = ARTIQDataReader(mode="simulated")
    for i in range(3):
        print(f"  [{i}] 强度: {reader.read_intensity():.2f}")

    print("\n=== 测试位置相关模拟 ===")
    for x in [-0.5, 0.0, 0.3, 0.7]:
        v = reader.read_intensity([x, -0.2, 0, 0])
        print(f"  pos=({x}, -0.2) 强度: {v:.2f}")
