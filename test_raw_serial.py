"""
Newton.S 位移台连接调试 - 底层通信测试

直接发送 SCPI 指令，查看设备原始响应。
"""

import sys
import time
import serial

PORT = "COM7"
BAUDRATE = 115200

print(f"{'='*50}")
print(f"  底层串口通信调试")
print(f"  串口: {PORT}, 波特率: {BAUDRATE}")
print(f"{'='*50}\n")

# 打开串口
ser = serial.Serial(PORT, BAUDRATE, timeout=2)
print(f"[OK] 串口已打开: {ser.name}")
time.sleep(0.5)

# 清空缓冲区
ser.reset_input_buffer()
ser.reset_output_buffer()

# 测试命令列表
commands = [
    "*IDN?\n",           # 标准 SCPI 识别
    "HARD:IDN?\n",       # Newton.S 硬件识别
    "SENS:POS?\n",       # 读取位置
    "STAT:MOVE?\n",      # 运动状态
    "STAT:TARG?\n",      # 目标状态
    "STAT:ERR?\n",       # 错误状态
]

for cmd in commands:
    print(f"\n--- 发送: {repr(cmd)} ---")
    ser.write(cmd.encode())
    time.sleep(0.1)  # 等待响应

    # 读取所有可用数据
    available = ser.in_waiting
    if available > 0:
        response = ser.read(available)
        print(f"    响应 ({available} bytes): {repr(response)}")
        try:
            print(f"    解码: {response.decode('utf-8', errors='replace').strip()}")
        except Exception:
            pass
    else:
        print(f"    无响应 (0 bytes)")
        # 再等一下试试
        time.sleep(0.2)
        available = ser.in_waiting
        if available > 0:
            response = ser.read(available)
            print(f"    延迟响应 ({available} bytes): {repr(response)}")
            try:
                print(f"    解码: {response.decode('utf-8', errors='replace').strip()}")
            except Exception:
                pass

# 尝试不同的换行符
print(f"\n\n--- 尝试不同换行符 ---")
for ending in ["\n", "\r\n", "\r"]:
    cmd = f"HARD:IDN?{ending}"
    ser.reset_input_buffer()
    ser.write(cmd.encode())
    time.sleep(0.15)
    available = ser.in_waiting
    response = ser.read(available) if available > 0 else b""
    print(f"  换行符 {repr(ending)}: 响应 {available} bytes = {repr(response[:80])}")

ser.close()
print(f"\n[OK] 串口已关闭")
