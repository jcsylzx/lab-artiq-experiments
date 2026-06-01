"""
快速测试脚本 - 验证GUI能否启动（不需要真实硬件）
"""

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

# 测试导入
print("测试模块导入...")
try:
    from multi_stage_controller import NewtonMS4Controller
    print("  [OK] multi_stage_controller")
except Exception as e:
    print(f"  [FAIL] multi_stage_controller: {e}")
    sys.exit(1)

try:
    from artiq_data_reader import ARTIQDataReader
    print("  [OK] artiq_data_reader")
except Exception as e:
    print(f"  [FAIL] artiq_data_reader: {e}")
    sys.exit(1)

try:
    from main_gui import MainWindow
    print("  [OK] main_gui")
except Exception as e:
    print(f"  [FAIL] main_gui: {e}")
    sys.exit(1)

# 测试数据读取器
print("\n测试数据读取器...")
reader = ARTIQDataReader(mode='simulated')
for i in range(3):
    intensity = reader.read_intensity()
    print(f"  读取 {i+1}: 强度 = {intensity:.2f}")

print("\n测试位移台模拟控制器...")
ctrl = NewtonMS4Controller(simulation=True)
assert ctrl.connect()
ctrl.move_to(0, 0.1, speed=1.0)
print(f"  模拟位置: {ctrl.get_all_positions()}")
ctrl.disconnect()

# 测试GUI启动（3秒后自动关闭）
print("\n测试GUI启动（3秒后自动关闭）...")
app = QApplication(sys.argv)
window = MainWindow()
window.show()

# 3秒后自动关闭
QTimer.singleShot(3000, app.quit)

print("  GUI已显示，3秒后自动关闭...")
app.exec_()

print("\n[OK] 所有测试通过！")
print("\n可以运行 'python main_gui.py' 或 'run.bat' 启动完整程序。")
