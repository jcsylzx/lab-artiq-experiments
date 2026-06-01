"""Standalone TTL counter that publishes to the ARTIQ master dataset DB.

Run this with artiq_run instead of submitting it to the ARTIQ scheduler. This
keeps the long-running TTL monitor out of the master worker while still making
the latest counts available to the GUI through dataset_db.
"""

from artiq.experiment import *
from artiq.language.core import kernel
from artiq.language.units import us, s
try:
    from artiq.experiment import TInt32, TFloat
except ImportError:
    from numpy import int32 as TInt32
    TFloat = float
try:
    from artiq.language.core import KernelInvariant, compile as artiq_compile
    from artiq.coredevice.core import Core
    from artiq.coredevice.ttl import TTLInOut
except ImportError:
    class KernelInvariant:
        def __class_getitem__(cls, item):
            return item
    Core = object
    TTLInOut = object
    def artiq_compile(cls):
        return cls
from sipyco.pc_rpc import Client
import time
import traceback

@artiq_compile
class TTLDatasetBridge(EnvExperiment):
    core: KernelInvariant[Core]
    ttl0: KernelInvariant[TTLInOut]
    ttl1: KernelInvariant[TTLInOut]
    ttl2: KernelInvariant[TTLInOut]
    ttl3: KernelInvariant[TTLInOut]
    ttl: KernelInvariant[TTLInOut]

    def build(self):
        self.setattr_device("core")
        self.setattr_device("ttl0")
        self.setattr_device("ttl1")
        self.setattr_device("ttl2")
        self.setattr_device("ttl3")

        self.setattr_argument(
            "ttl_channel",
            EnumerationValue(["ttl0", "ttl1", "ttl2", "ttl3"], default="ttl0"),
            "TTL input",
        )
        self.setattr_argument(
            "edge",
            EnumerationValue(["rising", "falling", "both"], default="rising"),
            "TTL input",
        )
        self.setattr_argument(
            "gate_time",
            NumberValue(100 * us, unit="us", min=1 * us, max=10 * s,
                        precision=3),
            "TTL input",
        )
        self.setattr_argument(
            "gate_subdivisions",
            NumberValue(1000, min=1, max=1000000, precision=0, step=1),
            "TTL input",
        )
        self.setattr_argument(
            "max_samples",
            NumberValue(0, min=0, max=100000000, precision=0, step=1),
            "TTL input",
        )
        self.setattr_argument(
            "batch_size",
            NumberValue(10, min=1, max=1000, precision=0, step=1),
            "TTL input",
        )
        self.setattr_argument(
            "master_host",
            StringValue("::1"),
            "ARTIQ master dataset RPC host",
        )
        self.setattr_argument(
            "master_port",
            NumberValue(3251, min=1, max=65535, precision=0, step=1),
            "ARTIQ master dataset RPC port",
        )

    def prepare(self):
        self.ttl = getattr(self, self.ttl_channel)
        self.gate_subdivisions = int(self.gate_subdivisions)
        if self.gate_subdivisions < 1:
            self.gate_subdivisions = 1

    @kernel
    def setup_ttl_input(self):
        self.core.break_realtime()
        self.ttl.input()

    @kernel
    def count_rising(self, gate_time: TFloat,
                     gates_per_batch: TInt32) -> TInt32:
        self.core.break_realtime()
        total = 0
        for _ in range(gates_per_batch):
            gate_end = self.ttl.gate_rising(gate_time)
            total += self.ttl.count(gate_end)
        return total

    @kernel
    def count_falling(self, gate_time: TFloat,
                      gates_per_batch: TInt32) -> TInt32:
        self.core.break_realtime()
        total = 0
        for _ in range(gates_per_batch):
            gate_end = self.ttl.gate_falling(gate_time)
            total += self.ttl.count(gate_end)
        return total

    @kernel
    def count_both(self, gate_time: TFloat,
                   gates_per_batch: TInt32) -> TInt32:
        self.core.break_realtime()
        total = 0
        for _ in range(gates_per_batch):
            gate_end = self.ttl.gate_both(gate_time)
            total += self.ttl.count(gate_end)
        return total

    @kernel
    def reset_core_after_error(self):
        self.core.reset()

    def publish(self, client, key, value):
        client.set(key, value, persist=False)

    def read_runtime_config_value(self, key, current, cast, lower, upper):
        try:
            value = self._dataset_client.get("ttl_monitor.config." + key)
        except Exception:
            return current
        try:
            value = cast(value)
        except Exception:
            return current
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

    def refresh_runtime_config(self):
        self._gate_time_s = self.read_runtime_config_value(
            "gate_time", self._gate_time_s, float, 1e-6, 10.0)
        self._gates_per_batch = self.read_runtime_config_value(
            "gate_subdivisions", self._gates_per_batch, int, 1, 1000000)
        self.publish(self._dataset_client, "ttl_monitor.gate_time",
                     float(self._gate_time_s))
        self.publish(self._dataset_client, "ttl_monitor.gate_subdivisions",
                     int(self._gates_per_batch))
        self.publish(self._dataset_client, "ttl_monitor.gates_per_batch",
                     int(self._gates_per_batch))

    def publish_sample(self, sample, total_count):
        total_count = int(total_count)
        gates = max(int(self._gates_per_batch), 1)
        effective_gate_time = self._gate_time_s * gates
        avg_count = total_count / gates
        rate = total_count / effective_gate_time if effective_gate_time > 0 else 0.0
        self.publish(self._dataset_client, "pulse_latest", float(avg_count))
        self.publish(self._dataset_client, "counts", float(avg_count))
        self.publish(self._dataset_client, "ttl_monitor.batch_total_counts",
                     total_count)
        self.publish(self._dataset_client, "ttl_monitor.batch_gate_count",
                     gates)
        self.publish(self._dataset_client, "ttl_monitor.effective_gate_time",
                     float(effective_gate_time))
        self.publish(self._dataset_client, "ttl_monitor.count_rate", float(rate))
        self.publish(self._dataset_client, "ttl_monitor.sample", int(sample))
        self.publish(self._dataset_client, "ttl_monitor.timestamp", time.time())
        self.publish(
            self._dataset_client,
            "ttl_monitor.ttl_channel",
            self.ttl_channel,
        )
        self.publish(self._dataset_client, "ttl_monitor.edge", self.edge)
        self.publish(self._dataset_client, "ttl_monitor.status", "running")
        self.publish(self._dataset_client, "ttl_monitor.error", "")

    def publish_error(self, error_count, exc):
        message = f"{exc.__class__.__name__}: {exc}"
        hint = ""
        if "input overflow" in message.lower():
            hint = (
                " TTLInOut is receiving more edge timestamp events than the "
                "RTIO input FIFO can hold. Reduce the input rate, shorten the "
                "gate, improve signal quality, or use an external divider/scaler."
            )
        self.publish(self._dataset_client, "ttl_monitor.status", "error")
        self.publish(self._dataset_client, "ttl_monitor.error", message + hint)
        self.publish(self._dataset_client, "ttl_monitor.error_count",
                     int(error_count))
        self.publish(self._dataset_client, "ttl_monitor.timestamp",
                     time.time())
        print(f"TTL bridge recovered from error #{error_count}: "
              f"{message}{hint}",
              flush=True)
        traceback.print_exc()

    def run(self):
        self._dataset_client = Client(
            str(self.master_host),
            int(self.master_port),
            "dataset_db",
        )
        max_samples = int(self.max_samples)
        self._gate_time_s = float(self.gate_time)
        gate_time_s = self._gate_time_s
        self._gates_per_batch = max(int(self.gate_subdivisions), 1)

        self.publish(self._dataset_client, "pulse_latest", 0)
        self.publish(self._dataset_client, "counts", 0)
        self.publish(self._dataset_client, "ttl_monitor.config.gate_time",
                     gate_time_s)
        self.publish(self._dataset_client, "ttl_monitor.config.gate_subdivisions",
                     int(self._gates_per_batch))
        self.publish(self._dataset_client, "ttl_monitor.count_rate", 0.0)
        self.publish(self._dataset_client, "ttl_monitor.sample", 0)
        self.publish(self._dataset_client, "ttl_monitor.timestamp", time.time())
        self.publish(self._dataset_client, "ttl_monitor.ttl_channel",
                     self.ttl_channel)
        self.publish(self._dataset_client, "ttl_monitor.edge", self.edge)
        self.publish(self._dataset_client, "ttl_monitor.gate_time", gate_time_s)
        self.publish(self._dataset_client, "ttl_monitor.gate_subdivisions",
                     int(self._gates_per_batch))
        self.publish(self._dataset_client, "ttl_monitor.gates_per_batch",
                     int(self._gates_per_batch))
        self.publish(self._dataset_client, "ttl_monitor.status", "starting")
        self.publish(self._dataset_client, "ttl_monitor.error", "")
        self.publish(self._dataset_client, "ttl_monitor.error_count", 0)

        print(f"Bridge {self.ttl_channel}: edge={self.edge}, "
              f"gate={gate_time_s:.6f}s, "
              f"gates_per_batch={int(self._gates_per_batch)}, "
              f"master={self.master_host}:{int(self.master_port)}")
        try:
            self.setup_ttl_input()
            sample = 0
            error_count = 0
            while max_samples == 0 or sample < max_samples:
                self.refresh_runtime_config()
                try:
                    if self.edge == "falling":
                        count = self.count_falling(
                            self._gate_time_s, int(self._gates_per_batch))
                    elif self.edge == "both":
                        count = self.count_both(
                            self._gate_time_s, int(self._gates_per_batch))
                    else:
                        count = self.count_rising(
                            self._gate_time_s, int(self._gates_per_batch))
                except Exception as exc:
                    error_count += 1
                    try:
                        self.publish_error(error_count, exc)
                    except Exception:
                        traceback.print_exc()
                    if isinstance(exc, (ConnectionError, OSError)):
                        raise
                    try:
                        self.reset_core_after_error()
                        self.setup_ttl_input()
                    except Exception:
                        traceback.print_exc()
                    time.sleep(0.5)
                    continue

                sample += 1
                self.publish_sample(sample, count)
        finally:
            try:
                self.publish(self._dataset_client, "ttl_monitor.status",
                             "stopped")
                self.publish(self._dataset_client, "ttl_monitor.timestamp",
                             time.time())
            except Exception:
                pass
            try:
                self._dataset_client.close_rpc()
            except Exception:
                pass
