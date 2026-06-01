"""
Newton.S 位移台连接测试

测试 COM7 串口连接是否正常，读取设备信息和当前位置。
"""

import sys
import time

# SDK 路径
sdk_path = "D:/0核钟/任务/artiq+多场/MCNewtonS-1.0.0-py3-none-any"
sys.path.insert(0, sdk_path)

from NewtonS.MCNewtonS import MCNewtonS, MFMCNewtonStatus

PORT = "COM7"

print(f"{'='*50}")
print(f"  Newton.S 位移台连接测试")
print(f"  串口: {PORT}")
print(f"{'='*50}\n")

# 1. 连接设备
print("[1] 连接设备...")
try:
    dev = MCNewtonS(PORT)
    if dev.device and dev.device.is_open:
        print(f"    [OK] 串口 {PORT} 已打开\n")
    else:
        print(f"    [FAIL] 串口打开失败")
        sys.exit(1)
except Exception as e:
    print(f"    [FAIL] 连接异常: {e}")
    sys.exit(1)

# 2. 读取硬件信息
print("[2] 读取硬件信息...")
try:
    status, info = dev.hard_idn()
    if status == MFMCNewtonStatus.NoError:
        print(f"    [OK] 设备信息: {info}")
    else:
        print(f"    [WARN] 读取失败, 状态码: {status}")
except Exception as e:
    print(f"    [WARN] 异常: {e}")

# 3. 读取当前位置
print("\n[3] 读取当前位置...")
try:
    status, pos = dev.sens_pos()
    if status == MFMCNewtonStatus.NoError:
        print(f"    [OK] 当前位置: {pos} mm")
    else:
        print(f"    [WARN] 读取位置失败, 状态码: {status}")
except Exception as e:
    print(f"    [WARN] 异常: {e}")

# 4. 读取运动状态
print("\n[4] 读取运动状态...")
try:
    status, moving = dev.stat_move()
    if status == MFMCNewtonStatus.NoError:
        print(f"    [OK] 运动状态: {'运动中' if moving else '静止'}")
    else:
        print(f"    [WARN] 状态码: {status}")
except Exception as e:
    print(f"    [WARN] 异常: {e}")

# 5. 读取目标状态
print("\n[5] 读取目标到达状态...")
try:
    status, on_target = dev.stat_targ()
    if status == MFMCNewtonStatus.NoError:
        print(f"    [OK] 到达目标: {'是' if on_target else '否'}")
    else:
        print(f"    [WARN] 状态码: {status}")
except Exception as e:
    print(f"    [WARN] 异常: {e}")

# 6. 读取错误状态
print("\n[6] 读取错误状态...")
try:
    status, err = dev.stat_err()
    if status == MFMCNewtonStatus.NoError:
        print(f"    [OK] 错误码: {err}")
    else:
        print(f"    [WARN] 状态码: {status}")
except Exception as e:
    print(f"    [WARN] 异常: {e}")

# 7. 断开连接
print(f"\n[7] 断开连接...")
dev.disconnect()
print(f"    [OK] 已断开")

print(f"\n{'='*50}")
print(f"  测试完成")
print(f"{'='*50}")
