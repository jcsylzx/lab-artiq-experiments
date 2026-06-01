# 项目运行架构与 ARTIQ 代码注解

本文对应 2026-06-01 连续 TTL 采样版本。当前程序不使用硬件边沿计数器方案，也不使用旧发布周期字段控制 ARTIQ 采样节奏。

## 1. 总体运行链路

程序运行时通常有三个窗口/进程：

1. `scripts/02_start_artiq_master.bat`
   启动 `artiq_master.exe`，提供 `device_db.py`、repository 和 dataset RPC 服务。

2. `scripts/03_start_ttl_bridge.bat`
   用 `artiq_run.exe` 运行 `artiq_repository/ttl_dataset_bridge.py`。这个 bridge 直接和 ARTIQ core/TTL 硬件交互，持续采集 TTL gate 计数，并把结果发布到 ARTIQ master 的 dataset DB。

3. `scripts/04_run_gui_artiq.bat`
   启动 `run_artiq_gui.py`，再进入 `main_gui.py`。GUI 负责位移台串口控制、读取 dataset、显示实时曲线、1D 曲线和 2D 热图。

核心数据流：

```text
TTL/PMT pulse -> ARTIQ ttl0 -> ttl_dataset_bridge.py
              -> ARTIQ dataset_db
              -> artiq_data_reader.py
              -> main_gui.py plots

Stage COM port -> multi_stage_controller.py
               -> main_gui.py positions
               -> 1D/2D plotting with latest TTL intensity
```

## 2. 当前 TTL 连续采样模型

`ttl_dataset_bridge.py` 的主循环不是“采一次、睡一段时间、再采一次”。当前逻辑是：

```text
启动时设置 TTL 输入模式
while running:
    读取 gate_time 和 gate_subdivisions
    在 ARTIQ core 里连续执行 gate_subdivisions 个 gate
    统计这一批总 count
    发布平均 count、总 count、count_rate、sample id
    立刻进入下一批
```

这里的 `gate_subdivisions` 在 GUI 中显示为“每批门数”，实际含义是 `gates_per_batch`。

例子：

```text
gate_time = 1 us
每批门数 = 1000
```

表示 ARTIQ core 连续执行 1000 个 1 us gate，得到这一批的总 count，再换算为平均频率。

已经删除的旧逻辑：

```text
旧发布周期参数
旧发布周期环境变量
旧 dataset 发布周期配置
每轮采样后的等待逻辑
每次 count 前重新设置输入模式和等待
```

GUI 里的 `GUI刷新(ms)` 只控制窗口多久读取一次 dataset 和刷新图像，不控制 ARTIQ 是否采样。

## 3. `main_gui.py`

`main_gui.py` 是用户界面和扫描状态机。

主要对象：

```python
self.controller = MultiStageController(...)
self.data_reader = ARTIQDataReader(mode="sipyco")
self.update_timer = QTimer()
self.scan_timer = QTimer()
```

`update_timer` 周期执行 `update_all()`：

1. 从位移台读取当前位置。
2. 通过 `ARTIQDataReader.read_intensity()` 读取最新 TTL 强度。
3. 更新实时曲线。
4. 如果正在扫描，把“当前位置 + 强度”送入 1D 或 2D 图。

`scan_timer` 周期执行 `scan_step()`：

1. 1D 模式下：先移动到起点，再单次移动到终点，到终点即停止。
2. 2D 模式下：先到左下角，再长轴连续扫一行，行末 Y 轴步进，下一行反向扫描，直到所有行完成。

2D 绘图不是简单按时间切像素，而是把相邻两次 ARTIQ 新 sample 对应的实际位移台位置连成一段，用这段经过的像素长度做加权平均。

## 4. `artiq_data_reader.py`

这个文件是 GUI 和 ARTIQ dataset DB 之间的适配器，不直接操作硬件。

连接：

```python
from sipyco.pc_rpc import Client
Client(master_host, master_port, "dataset_db")
```

读取强度：

```python
read_intensity()
  -> _read_from_sipyco()
  -> 读取 ttl_monitor.count_rate / pulse_latest / counts
  -> 换算为 kHz
```

运行时 TTL 参数写入：

```python
set_ttl_config(gate_time, gate_subdivisions)
```

只写入：

```text
ttl_monitor.config.gate_time
ttl_monitor.config.gate_subdivisions
```

不再写入任何旧发布周期字段。

`ttl_monitor.sample` 用于判断是否出现了新的 ARTIQ 样本。2D 扫描只在 sample id 更新时写入新的图像数据。

## 5. `multi_stage_controller.py`

这个文件负责和位移台控制器通信。GUI 通过它调用：

```python
connect()
disconnect()
move_to(channel, target, speed)
stop(channel)
stop_all()
get_position(channel)
get_all_positions()
is_on_target(channel)
get_error(channel)
clear_error(channel)
```

通道 0、1 是位置轴，单位 mm；通道 2、3 是角度轴，单位 degree。

## 6. `artiq_repository/ttl_dataset_bridge.py`

这是当前实际运行的 ARTIQ 采集脚本。

### 6.1 `build()`

注册设备：

```python
self.setattr_device("core")
self.setattr_device("ttl0")
self.setattr_device("ttl1")
self.setattr_device("ttl2")
self.setattr_device("ttl3")
```

注册参数：

```python
ttl_channel        # ttl0/ttl1/ttl2/ttl3
edge               # rising/falling/both
gate_time          # 单个 gate 门宽
gate_subdivisions  # 每批门数，也就是 gates_per_batch
max_samples        # 0 表示无限运行
batch_size         # 当前保留参数，不参与主采样节奏
master_host
master_port
```

### 6.2 `prepare()`

```python
self.ttl = getattr(self, self.ttl_channel)
```

把字符串形式的 `ttl0` 转换为实际 TTL 设备对象。

### 6.3 `setup_ttl_input()`

```python
self.core.break_realtime()
self.ttl.input()
```

只在 bridge 启动时执行一次。发生错误并 reset core 后会再执行一次。正常每批采样前不会重复切输入模式，也不会插入固定等待。

### 6.4 `count_rising()`

```python
self.core.break_realtime()
total = 0
for _ in range(gates_per_batch):
    gate_end = self.ttl.gate_rising(gate_time)
    total += self.ttl.count(gate_end)
return total
```

这段在 ARTIQ core 上运行。它连续执行多个 gate，并返回这一批的总 count。

`count_falling()` 和 `count_both()` 结构相同，只是换成下降沿或双沿 gate。

### 6.5 `refresh_runtime_config()`

每批采样前从 dataset DB 读取：

```text
ttl_monitor.config.gate_time
ttl_monitor.config.gate_subdivisions
```

这样 GUI 修改门宽或每批门数后，不需要重启 bridge。

### 6.6 `publish_sample()`

将一批采样结果发布为 datasets：

```text
pulse_latest
counts
ttl_monitor.batch_total_counts
ttl_monitor.batch_gate_count
ttl_monitor.effective_gate_time
ttl_monitor.count_rate
ttl_monitor.sample
ttl_monitor.timestamp
ttl_monitor.ttl_channel
ttl_monitor.edge
ttl_monitor.status
ttl_monitor.error
```

`ttl_monitor.count_rate` 是 Hz，GUI 读到后换算为 kHz 显示。

### 6.7 `run()`

主循环：

```text
连接 dataset_db
初始化 datasets
setup_ttl_input()
while max_samples == 0 or sample < max_samples:
    refresh_runtime_config()
    根据 edge 调用 count_rising/count_falling/count_both
    publish_sample()
```

循环中没有按旧发布周期等待。

错误处理：

1. 发布 `ttl_monitor.status = error`。
2. 发布 `ttl_monitor.error`。
3. 如果是普通 RTIO/TTL 错误，尝试 `core.reset()` 并重新 `setup_ttl_input()`。
4. 错误恢复前有 `time.sleep(0.5)`，这是异常恢复保护，不属于正常采样节奏。

## 7. `artiq_master/device_db.py`

`device_db.py` 定义 ARTIQ core 地址和 TTL 设备映射。GUI 不直接读取它，但 `artiq_master.exe` 和 `artiq_run.exe` 依赖它找到 `core`、`ttl0` 等设备。

关键作用：

```text
core_addr = ARTIQ 核心设备 IP
ttl0/ttl1/ttl2/ttl3 = TTLInOut 输入输出通道
```

如果换电脑或换 ARTIQ IP，先检查这里和 `portable_config.bat` 中的 `ARTIQ_CORE_ADDR` 是否一致。

## 8. 当前精简包中保留的 ARTIQ 脚本

精简包只保留运行主程序必需的：

```text
artiq_repository/ttl_dataset_bridge.py
artiq_master/repository/ttl_dataset_bridge.py
```

旧的 1D/2D ARTIQ 原生扫描脚本、TTL monitor/probe 脚本和硬件边沿计数器模板不属于当前运行主链路，已从精简包移除，避免旧参数和旧延迟逻辑造成混淆。
