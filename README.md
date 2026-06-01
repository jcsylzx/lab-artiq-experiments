# 多通道位移台 + ARTIQ 集成控制系统 v2.1

用于在同一个 PyQt 界面中操作 MC-Newton.MSx 四通道位移台，并实时读取/显示 ARTIQ 脉冲计数信号。

## 当前功能

- 四通道位移台独立控制：位置读取、目标移动、点动、停止、紧急停止
- 通道单位区分：通道 0/1 为位移 `mm`，通道 2/3 为角度 `°`
- Error 状态显示：每个通道显示 `STAT:ERR?`，顶部显示汇总，并可手动执行清除/复位
- 实时信号页：手动移动位移台时也能观察脉冲强度随时间变化
- 1D 扫描：启用的通道从起点扫到终点，单次完成后自动停止
- 2D 扫描：选择两个通道作 X/Y 轴，蛇形光栅扫描单个区域，完成后自动停止
- ARTIQ 数据源可配置：`sipyco`、`hdf5`、`simulated`
- 位移台控制器兼容 MSx 多通道 `N-COMMAND` 协议，例如 `1-MOVE:CLOS ...`、`1-SENS:POS?`
- 无硬件调试：COM 口输入 `SIM` 可启用模拟位移台，并自动连接 `simulated` 数据源

## 文件结构

```text
multi_stage_gui/
├── main_gui.py                 # 主界面
├── multi_stage_controller.py   # MC-Newton.MSx 四通道串口控制器
├── artiq_data_reader.py        # ARTIQ dataset/HDF5/模拟数据读取器
├── artiq_repository/
│   └── ttl_signal_monitor.py   # ARTIQ 侧连续 TTL 计数实验
│   └── ttl_dataset_bridge.py    # 推荐：artiq_run 直跑并发布实时 TTL dataset
│   └── ttl_input_probe.py       # TTL 输入硬件探针
├── artiq_ttl_debug.py          # ARTIQ core/master/dataset 诊断脚本
├── run_artiq_gui.py            # 使用 ARTIQ Python 环境启动 GUI
├── run_artiq_gui.bat           # ARTIQ 环境启动脚本
├── set_artiq_ip_admin.bat      # 管理员运行：设置以太网到 192.168.1.100/24
├── start_artiq_master.bat      # 启动本机 ARTIQ master
├── submit_ttl_monitor.bat      # 提交连续 TTL 计数实验
├── start_ttl_bridge.bat        # 推荐：启动独立 TTL dataset bridge
├── test_gui.py                 # GUI 启动前自检
├── test_connection.py          # SDK 单轴连接测试
├── test_raw_serial.py          # 底层串口命令测试
└── run.bat                     # Windows 启动脚本
```

## 依赖

```bash
pip install pyserial PyQt5 pyqtgraph numpy sipyco h5py
```

如果只做模拟 GUI 测试，`sipyco` 和 `h5py` 可以暂时不装；连接真实 ARTIQ master 时需要 `sipyco`。

## 启动

```bash
cd "D:\0核钟\任务\artiq+多场\multi_stage_gui"
python main_gui.py
```

或双击 `run.bat`。

连接真实 ARTIQ 时，推荐双击 `run_artiq_gui.bat`。它会使用
`E:\msys64\clang64\bin\python.exe` 启动 GUI，从而获得 `artiq/sipyco`
支持；同时会把普通 Windows Python 中已有的 `pyserial` 追加进路径，用于
位移台串口控制。

## 连接位移台

1. 在顶部 `COM口` 输入真实串口号，例如 `COM7`。
2. 点击 `连接`。
3. 如果要无硬件测试，输入 `SIM` 后点击 `连接`，程序会自动切到并连接模拟数据源。

位移台命令按手册使用多通道前缀：

```text
1-MOVE:CLOS 1.000000,1.000000,10.000000,10.000000
1-MOVE:JOG 0.010000,0,1.000000,10.000000,10.000000
1-SENS:POS?
1-STAT:TARG?
```

`清除/复位Error` 按钮会先停止所有通道，再发送 `HARD:REST`，然后重新查询 `STAT:ERR?`。这是根据手册中错误查询/复位命令实现的，不只是隐藏界面提示。

## 连接 ARTIQ 数据源

界面第二行是 ARTIQ 数据栏：

- `sipyco`：通过 ARTIQ master 的 dataset RPC 读取实时 dataset，默认 host `::1`、port `3251`
- `simulated`：生成位置相关模拟信号，适合调 GUI 和扫描流程
- `hdf5`：读取最近的 ARTIQ HDF5 结果文件

`Dataset` 可填写具体 dataset 名；填 `auto` 时会依次尝试：

```text
pulse_latest, counts, count, ttl_monitor.count_rate, ttl_monitor.count_history,
latest_counts, scan.latest, scan.intensity, scan2d.image
```

现有 `D:\0核钟\任务\artiq_master\repository` 中的扫描实验会广播：

```text
scan.intensity
scan.progress
scan2d.image
scan2d.progress
```

因此使用 `auto` 或直接填写 `scan.intensity` / `scan2d.image` 都可以读取已有扫描实验数据。若希望 GUI 手动移动位移台、ARTIQ 只持续计数，建议在 ARTIQ 侧再运行一个持续更新 `pulse_latest` 或 `counts` 的计数实验。

本项目已提供该计数实验：

```text
multi_stage_gui\artiq_repository\ttl_signal_monitor.py
```

把它复制到：

```text
D:\0核钟\任务\artiq_master\repository\ttl_signal_monitor.py
```

然后在 ARTIQ dashboard 或 `artiq_client` 中运行。实验可选择 `ttl0` 到
`ttl3`，并持续广播：

```text
pulse_latest
counts
ttl_monitor.count_rate
ttl_monitor.count_history
ttl_monitor.rate_history
```

GUI 的 `Dataset` 填 `auto` 时会优先读取这些实时计数数据。

## ARTIQ 网口与 TTL 调试

当前 `D:\0核钟\任务\artiq_master\device_db.py` 中 core 地址为：

```text
192.168.1.75
```

电脑直连 ARTIQ core 时，以太网口需要手动设在同一网段，例如：

```powershell
netsh interface ip set address name="以太网" static 192.168.1.100 255.255.255.0
```

设好后可运行诊断：

```powershell
cd "D:\0核钟\任务\artiq+多场\multi_stage_gui"
E:\msys64\clang64\bin\python.exe artiq_ttl_debug.py --core 192.168.1.75 --master ::1
```

也可以按顺序使用脚本：

1. 右键管理员运行 `set_artiq_ip_admin.bat`
2. 双击 `start_artiq_master.bat`，保持窗口运行
3. 双击 `start_ttl_bridge.bat`
4. 双击 `run_artiq_gui.bat`，GUI 中 ARTIQ 数据源选择 `sipyco`，`Dataset` 填 `auto`

若 `ttl_signal_monitor.py` 正在运行，可继续观察 dataset：

```powershell
E:\msys64\clang64\bin\python.exe artiq_ttl_debug.py --skip-core --watch --seconds 10
```

注意：当 `ttl_dataset_bridge.py` 这类长 kernel 正在运行时，不要用诊断脚本探测 core
端口；请加 `--skip-core`，只观察 master dataset。直接探测 core 端口可能打断正在运行的
kernel。

## 使用建议

- 手动调位移台时，打开 `实时信号` tab 观察脉冲强度随时间变化。
- 通道 0/1 的目标、步长、扫描范围单位为 `mm`；通道 2/3 的单位为 `°`，速度对应为 `°/s`。
- 做 1D 扫描时，在需要扫描的通道勾选 `启用1D扫描`，设置起点/终点/速度，再点击 `开始扫描`；到终点后会自动停止。
- 做 2D 热图时，选择不同的 X/Y 通道，设置范围、网格和速度，再点击 `开始扫描`；扫完整个区域后会自动停止。
- 2D 网格过大时，成图会很慢；调试阶段建议先用 20-80。

## 快速自检

```bash
python -m py_compile main_gui.py multi_stage_controller.py artiq_data_reader.py
python artiq_data_reader.py
```

GUI 无硬件联调：

1. 启动 `python main_gui.py`
2. COM 口填 `SIM` 并连接
3. 观察数据栏显示 `数据源已连接: simulated`
4. 移动通道或启动扫描，观察实时信号、1D 曲线或 2D 热图
