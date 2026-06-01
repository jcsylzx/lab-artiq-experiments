"""
Newton.S MSx 多通道位移台控制器。

MC-Newton.MSx 手册中的多通道命令格式为 N-COMMAND，例如：
    1-MOVE:CLOS 1.234567,2,5,5
    1-SENS:POS?

为了兼容早期调试脚本，本控制器也能解析少数设备/固件可能返回的
"SENS:POS v0,v1,v2,v3" 聚合格式。
"""

import re
import time
import threading
from typing import List, Optional

import serial


_FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


class NewtonMS4Controller:
    """MC-Newton.MSx 四通道位移台控制器。"""

    def __init__(
        self,
        port: str = "COM7",
        baudrate: int = 115200,
        timeout: float = 0.08,
        response_timeout: float = 0.25,
        simulation: bool = False,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.response_timeout = response_timeout
        self.simulation = simulation
        self.device: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self.connected = False
        self.num_channels = 4
        self._aggregate_position_query: Optional[bool] = None
        self._aggregate_status_query: Optional[bool] = None

        self._sim_positions = [0.0] * self.num_channels
        self._sim_targets = [0.0] * self.num_channels
        self._sim_speeds = [1.0] * self.num_channels
        self._sim_last_update = time.time()

    # ----------------------------------------------------------------
    # 连接
    # ----------------------------------------------------------------
    def connect(self) -> bool:
        """连接设备；simulation=True 时不打开串口。"""
        if self.simulation:
            self.connected = True
            self._sim_last_update = time.time()
            return True

        try:
            self.device = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
                write_timeout=1.0,
            )
            if self.device.is_open:
                self.connected = True
                time.sleep(0.2)
                self.device.reset_input_buffer()
                self.device.reset_output_buffer()
                return True
        except serial.SerialException as exc:
            print(f"连接失败 {self.port}: {exc}")
        return False

    def disconnect(self):
        """断开连接。"""
        if self.device and self.device.is_open:
            self.device.close()
        self.connected = False

    # ----------------------------------------------------------------
    # 底层通信与解析
    # ----------------------------------------------------------------
    def _ch(self, channel: int) -> str:
        """内部 0-3 通道号转成设备 1-4 通道号。"""
        if not 0 <= int(channel) < self.num_channels:
            raise ValueError(f"非法通道号: {channel}")
        return str(int(channel) + 1)

    def _send_command(
        self,
        cmd: str,
        *,
        expect_response: bool = True,
        response_timeout: Optional[float] = None,
    ) -> Optional[str]:
        """发送命令；查询命令返回设备响应，执行命令默认不等待响应。"""
        if not self.connected or not self.device:
            return None

        deadline = time.time() + (response_timeout or self.response_timeout)
        with self._lock:
            try:
                self.device.reset_input_buffer()
                self.device.write(f"{cmd}\n".encode("ascii"))
                self.device.flush()
                if not expect_response:
                    return None

                chunks = []
                while time.time() < deadline:
                    available = self.device.in_waiting
                    if available:
                        data = self.device.read(available)
                        chunks.append(data)
                        if b"\n" in data or b"\r" in data:
                            break
                    else:
                        time.sleep(0.01)

                if not chunks:
                    return None
                return b"".join(chunks).decode("utf-8", errors="replace").strip()
            except Exception as exc:
                print(f"通信错误({cmd}): {exc}")
                return None

    @staticmethod
    def _pick_line(response: Optional[str], prefix: str = "") -> Optional[str]:
        if not response:
            return None
        lines = [line.strip() for line in response.replace("\r", "\n").split("\n")]
        lines = [line for line in lines if line]
        if prefix:
            for line in lines:
                if prefix in line:
                    return line
        return lines[-1] if lines else None

    @classmethod
    def _parse_scalar(cls, response: Optional[str], prefix: str = "") -> Optional[float]:
        """解析单个数值，兼容 '1-SENS:POS1.23' 与 '1-SENS:POS 1.23'。"""
        line = cls._pick_line(response, prefix)
        if not line:
            return None

        text = line
        if prefix and prefix in text:
            text = text.split(prefix, 1)[1]
        match = _FLOAT_RE.search(text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None

    @classmethod
    def _parse_values(
        cls,
        response: Optional[str],
        prefix: str = "",
        expected: int = 4,
    ) -> Optional[List[float]]:
        """解析逗号分隔的多值响应。"""
        line = cls._pick_line(response, prefix)
        if not line:
            return None
        text = line.split(prefix, 1)[1] if prefix and prefix in line else line
        values = []
        for token in text.split(","):
            match = _FLOAT_RE.search(token)
            if match:
                values.append(float(match.group(0)))
        if len(values) == expected:
            return values
        return None

    def _query_channel_scalar(self, channel: int, command: str) -> Optional[float]:
        dev_ch = self._ch(channel)
        prefix = f"{dev_ch}-{command.rstrip('?')}"
        response = self._send_command(f"{dev_ch}-{command}")
        return self._parse_scalar(response, prefix)

    def _query_all_status(self, command: str) -> Optional[List[int]]:
        """查询四个通道状态；优先使用已探测出的协议。"""
        if self.simulation:
            self._sim_update_all()
            if command == "STAT:MOVE?":
                return [
                    int(abs(p - t) > 1e-6)
                    for p, t in zip(self._sim_positions, self._sim_targets)
                ]
            if command == "STAT:TARG?":
                return [
                    int(abs(p - t) <= 1e-6)
                    for p, t in zip(self._sim_positions, self._sim_targets)
                ]
            if command == "STAT:ERR?":
                return [0] * self.num_channels

        if self._aggregate_status_query is not False:
            response = self._send_command(command)
            values = self._parse_values(response, command.rstrip("?"))
            if values is not None:
                self._aggregate_status_query = True
                return [int(v) for v in values]
            if self._aggregate_status_query is None:
                self._aggregate_status_query = False

        values = []
        for ch in range(self.num_channels):
            value = self._query_channel_scalar(ch, command)
            values.append(int(value) if value is not None else None)
        return values if any(v is not None for v in values) else None

    # ----------------------------------------------------------------
    # 位置读取
    # ----------------------------------------------------------------
    def get_all_positions(self) -> Optional[List[float]]:
        """读取所有通道位置，返回 [pos0, pos1, pos2, pos3]。"""
        if self.simulation:
            self._sim_update_all()
            return list(self._sim_positions)

        if self._aggregate_position_query is not False:
            response = self._send_command("SENS:POS?")
            values = self._parse_values(response, "SENS:POS")
            if values is not None:
                self._aggregate_position_query = True
                return values
            if self._aggregate_position_query is None:
                self._aggregate_position_query = False

        positions = [self.get_position(ch) for ch in range(self.num_channels)]
        return positions if any(pos is not None for pos in positions) else None

    def get_position(self, channel: int) -> Optional[float]:
        """读取指定通道位置。"""
        if self.simulation:
            self._sim_update_all()
            return self._sim_positions[int(channel)]
        return self._query_channel_scalar(channel, "SENS:POS?")

    # ----------------------------------------------------------------
    # 运动状态
    # ----------------------------------------------------------------
    def get_move_status(self) -> Optional[List[int]]:
        """读取运动状态：[0=静止, 1=运动中] x4。"""
        return self._query_all_status("STAT:MOVE?")

    def get_target_status(self) -> Optional[List[int]]:
        """读取目标到达状态 x4。"""
        return self._query_all_status("STAT:TARG?")

    def is_on_target(self, channel: int) -> bool:
        """检查指定通道是否到达目标。"""
        if self.simulation:
            self._sim_update_all()
            ch = int(channel)
            return abs(self._sim_positions[ch] - self._sim_targets[ch]) <= 1e-6

        value = self._query_channel_scalar(channel, "STAT:TARG?")
        if value is not None:
            return bool(int(value))

        status = self.get_target_status()
        return bool(status and 0 <= channel < len(status) and status[channel])

    def get_error_status(self) -> Optional[List[int]]:
        """读取错误状态 x4。"""
        return self._query_all_status("STAT:ERR?")

    def clear_error(self) -> bool:
        """
        清除/复位错误状态。

        手册没有列出单独的 ERR:CLR 命令；错误相关只给出 STAT:ERR?，
        复位命令为 HARD:REST。因此这里采用保守顺序：先停止所有通道，
        再发全局 HARD:REST，并让上层重新轮询 STAT:ERR?。
        """
        if self.simulation:
            return True
        if not self.connected:
            return False
        self.stop_all()
        self._send_command("HARD:REST", expect_response=False)
        self._aggregate_position_query = None
        self._aggregate_status_query = None
        time.sleep(0.2)
        return True

    # ----------------------------------------------------------------
    # 移动控制
    # ----------------------------------------------------------------
    def move_to(
        self,
        channel: int,
        target: float,
        speed: float = 1.0,
        acc: float = 10.0,
        dec: float = 10.0,
    ) -> bool:
        """闭环移动指定通道到目标位置。"""
        if self.simulation:
            self._sim_update_all()
            ch = int(channel)
            self._sim_targets[ch] = float(target)
            self._sim_speeds[ch] = max(abs(float(speed)), 1e-6)
            return True

        cmd = (
            f"{self._ch(channel)}-MOVE:CLOS "
            f"{target:.6f},{speed:.6f},{acc:.6f},{dec:.6f}"
        )
        self._send_command(cmd, expect_response=False)
        return True

    def move_jog(
        self,
        channel: int,
        step: float,
        speed: float = 1.0,
        acc: float = 10.0,
        dec: float = 10.0,
    ) -> bool:
        """步进移动指定通道；step 正负表示方向。"""
        if self.simulation:
            self._sim_update_all()
            ch = int(channel)
            self._sim_targets[ch] = self._sim_positions[ch] + float(step)
            self._sim_speeds[ch] = max(abs(float(speed)), 1e-6)
            return True

        cmd = (
            f"{self._ch(channel)}-MOVE:JOG "
            f"{step:.6f},0,{speed:.6f},{acc:.6f},{dec:.6f}"
        )
        self._send_command(cmd, expect_response=False)
        return True

    def stop(self, channel: int) -> bool:
        """停止指定通道。"""
        if self.simulation:
            self._sim_update_all()
            ch = int(channel)
            self._sim_targets[ch] = self._sim_positions[ch]
            return True

        self._send_command(
            f"{self._ch(channel)}-MOVE:STOP",
            expect_response=False,
        )
        return True

    def stop_all(self):
        """停止所有通道。"""
        for channel in range(self.num_channels):
            self.stop(channel)

    # ----------------------------------------------------------------
    # 设备信息
    # ----------------------------------------------------------------
    def get_hardware_info(self) -> Optional[str]:
        """读取硬件信息。"""
        return self._send_command("HARD:IDN?", response_timeout=0.7)

    def wait_on_target(self, channel: int, timeout: float = 30.0) -> bool:
        """阻塞等待通道到达目标。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.is_on_target(channel):
                return True
            time.sleep(0.05)
        return False

    # ----------------------------------------------------------------
    # 模拟模式
    # ----------------------------------------------------------------
    def _sim_update_all(self):
        now = time.time()
        dt = max(now - self._sim_last_update, 0.0)
        self._sim_last_update = now
        for ch in range(self.num_channels):
            pos = self._sim_positions[ch]
            target = self._sim_targets[ch]
            delta = target - pos
            if abs(delta) <= 1e-6:
                self._sim_positions[ch] = target
                continue
            step = self._sim_speeds[ch] * dt
            if abs(delta) <= step:
                self._sim_positions[ch] = target
            else:
                self._sim_positions[ch] += step if delta > 0 else -step


if __name__ == "__main__":
    print("Newton MSx 控制器测试")
    ctrl = NewtonMS4Controller(port="COM7")
    if ctrl.connect():
        print("[OK] 已连接")
        print(f"硬件: {ctrl.get_hardware_info()}")
        print(f"位置: {ctrl.get_all_positions()}")
        print(f"运动: {ctrl.get_move_status()}")
        print(f"目标: {ctrl.get_target_status()}")
        print(f"错误: {ctrl.get_error_status()}")
        ctrl.disconnect()
        print("[OK] 已断开")
    else:
        print("[FAIL] 连接失败")
