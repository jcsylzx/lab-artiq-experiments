"""
多通道位移台 + ARTIQ 集成控制界面

功能：
- 4通道紧凑控制（2x2网格）
- 1D扫描模式：脉冲强度 vs 位置曲线
- 2D扫描模式：选两个通道作X/Y，灰度热图实时上色
"""

import sys
import time
import os
import re
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QLineEdit,
                             QPushButton, QGroupBox, QComboBox, QCheckBox,
                             QDoubleSpinBox, QSpinBox, QTabWidget, QFrame,
                             QFileDialog)
from PyQt5.QtCore import QTimer, QSettings
from PyQt5.QtGui import QPalette, QColor, QFont
import pyqtgraph as pg
import pyqtgraph.exporters

from multi_stage_controller import NewtonMS4Controller
from artiq_data_reader import ARTIQDataReader


CHANNEL_COLORS = ['#ff5555', '#55ff55', '#5599ff', '#ffcc00']
CHANNEL_NAMES = ['位置', '位置', '角度', '角度']
CHANNEL_UNITS = ['mm', 'mm', '°', '°']
CHANNEL_SPEED_UNITS = ['mm/s', 'mm/s', '°/s', '°/s']


def channel_label(channel):
    return f'{CHANNEL_NAMES[channel]}({CHANNEL_UNITS[channel]})'


def make_spin(val, lo=-100.0, hi=100.0, dec=4, step=0.01, width=80):
    """创建紧凑的数字输入框"""
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setFixedWidth(width)
    return s


class ChannelPanel(QGroupBox):
    """单通道紧凑控制面板（一个GroupBox，所有控件在一个网格里）"""

    def __init__(self, channel_id, parent=None):
        color = CHANNEL_COLORS[channel_id]
        super().__init__(f'通道 {channel_id} ({CHANNEL_NAMES[channel_id]})', parent)
        self.setStyleSheet(
            f'QGroupBox{{border:2px solid {color};border-radius:6px;'
            f'margin-top:10px;padding-top:10px;font-weight:bold;}}'
            f'QGroupBox::title{{color:{color};subcontrol-origin:margin;'
            f'left:10px;padding:0 4px;}}'
        )
        self.channel_id = channel_id
        self.controller = None  # 由 MainWindow 注入
        self.unit = CHANNEL_UNITS[channel_id]
        self.speed_unit = CHANNEL_SPEED_UNITS[channel_id]

        g = QGridLayout()
        g.setContentsMargins(6, 6, 6, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)

        # 第0行：当前位置（大号显示）
        g.addWidget(QLabel(f'{CHANNEL_NAMES[channel_id]}({self.unit}):'), 0, 0)
        self.pos_display = QLineEdit('--')
        self.pos_display.setReadOnly(True)
        self.pos_display.setStyleSheet(
            f'color:{color};font-weight:bold;font-size:14px;')
        g.addWidget(self.pos_display, 0, 1, 1, 3)

        # 第1行：移动到目标
        g.addWidget(QLabel(f'目标({self.unit}):'), 1, 0)
        self.target_input = make_spin(0.0)
        g.addWidget(self.target_input, 1, 1)
        self.move_btn = QPushButton('移动')
        self.move_btn.setFixedWidth(60)
        self.move_btn.clicked.connect(self.on_move_to_target)
        g.addWidget(self.move_btn, 1, 2)
        self.stop_btn = QPushButton('停止')
        self.stop_btn.setFixedWidth(60)
        self.stop_btn.clicked.connect(self.on_stop)
        g.addWidget(self.stop_btn, 1, 3)

        # 第2行：点动
        g.addWidget(QLabel(f'步长({self.unit}):'), 2, 0)
        self.jog_step = make_spin(0.01, lo=0.0001, hi=10.0)
        g.addWidget(self.jog_step, 2, 1)
        self.jog_minus = QPushButton('◀')
        self.jog_plus = QPushButton('▶')
        self.jog_minus.setFixedWidth(60)
        self.jog_plus.setFixedWidth(60)
        self.jog_minus.clicked.connect(lambda: self.on_jog(-1))
        self.jog_plus.clicked.connect(lambda: self.on_jog(+1))
        g.addWidget(self.jog_minus, 2, 2)
        g.addWidget(self.jog_plus, 2, 3)

        # 第3行：1D扫描参数
        g.addWidget(QLabel('扫描:'), 3, 0)
        self.scan_start = make_spin(-1.0)
        self.scan_end = make_spin(1.0)
        g.addWidget(self.scan_start, 3, 1)
        g.addWidget(self.scan_end, 3, 2)
        self.scan_speed = make_spin(1.0, lo=0.001, hi=100.0, dec=3, step=0.1)
        g.addWidget(self.scan_speed, 3, 3)

        # 第4行：启用 + 速度标签
        self.scan_enable = QCheckBox('启用1D扫描')
        self.scan_enable.setChecked(channel_id == 0)
        g.addWidget(self.scan_enable, 4, 0, 1, 2)
        g.addWidget(QLabel(f'(起 / 终 / 速度{self.speed_unit})'), 4, 2, 1, 2)

        # 第5行：错误状态
        g.addWidget(QLabel('Error:'), 5, 0)
        self.error_display = QLineEdit('--')
        self.error_display.setReadOnly(True)
        self.error_display.setStyleSheet('color:#aaa;font-weight:bold;')
        g.addWidget(self.error_display, 5, 1, 1, 3)

        self.setLayout(g)

    def on_move_to_target(self):
        if self.controller and self.controller.connected:
            self.controller.move_to(self.channel_id, self.target_input.value(),
                                    speed=self.scan_speed.value())

    def on_stop(self):
        if self.controller and self.controller.connected:
            self.controller.stop(self.channel_id)

    def on_jog(self, direction):
        if self.controller and self.controller.connected:
            self.controller.move_jog(self.channel_id,
                                     self.jog_step.value() * direction)

    def update_position(self, position):
        if position is not None:
            self.pos_display.setText(f'{position:.6f}')
        else:
            self.pos_display.setText('--')

    def update_error(self, error_code):
        if error_code is None:
            self.error_display.setText('--')
            self.error_display.setStyleSheet('color:#aaa;font-weight:bold;')
        elif int(error_code) == 0:
            self.error_display.setText('0')
            self.error_display.setStyleSheet('color:#66dd66;font-weight:bold;')
        else:
            self.error_display.setText(str(int(error_code)))
            self.error_display.setStyleSheet('color:#ff5555;font-weight:bold;')


class Plot1D(QWidget):
    """1D 模式：脉冲强度 vs 位置（4条曲线）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', '脉冲计数')
        self.plot_widget.setLabel('bottom', '位置 / 角度', units='mm / °')
        self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        self.curves = []
        for i, c in enumerate(CHANNEL_COLORS):
            curve = self.plot_widget.plot(pen=pg.mkPen(c, width=2),
                                          symbol='o',
                                          symbolSize=5,
                                          symbolBrush=c,
                                          symbolPen=c,
                                          name=f'通道{i}')
            self.curves.append(curve)

        layout.addWidget(self.plot_widget)

        ctrl = QHBoxLayout()
        self.clear_btn = QPushButton('清除曲线')
        self.clear_btn.clicked.connect(self.clear)
        ctrl.addWidget(self.clear_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.setLayout(layout)
        self.data = {i: {'pos': [], 'I': []} for i in range(4)}
        self.max_points = 1000

    def add_point(self, channel, pos, intensity):
        d = self.data[channel]
        d['pos'].append(pos)
        d['I'].append(intensity)
        if len(d['pos']) > self.max_points:
            d['pos'] = d['pos'][-self.max_points:]
            d['I'] = d['I'][-self.max_points:]
        self.curves[channel].setData(d['pos'], d['I'])

    def clear(self):
        for i in range(4):
            self.data[i]['pos'].clear()
            self.data[i]['I'].clear()
            self.curves[i].setData([], [])

    def has_data(self):
        return any(self.data[i]['pos'] for i in range(4))

    def export_csv(self, path):
        with open(path, 'w', encoding='utf-8-sig') as handle:
            handle.write('channel,position,intensity_khz\n')
            for channel in range(4):
                pos_data = self.data[channel]['pos']
                intensity_data = self.data[channel]['I']
                for pos, intensity in zip(pos_data, intensity_data):
                    handle.write(
                        f'{channel},{float(pos):.12g},{float(intensity):.12g}\n')


class PlotLive(QWidget):
    """实时脉冲强度 vs 时间，用于手动移动时观察信号变化。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', '脉冲计数')
        self.plot_widget.setLabel('bottom', '时间', units='s')
        left_axis = self.plot_widget.getAxis('left')
        if hasattr(left_axis, 'enableAutoSIPrefix'):
            left_axis.enableAutoSIPrefix(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen('#ffffff', width=2),
            symbol='o',
            symbolSize=5,
            symbolBrush='#ffffff',
            symbolPen='#ffffff',
            name='实时强度')
        layout.addWidget(self.plot_widget, 1)

        ctrl = QHBoxLayout()
        self.latest_label = QLabel('最新强度: --')
        self.latest_label.setStyleSheet('font-weight:bold;font-size:14px;')
        ctrl.addWidget(self.latest_label)
        ctrl.addStretch()
        self.clear_btn = QPushButton('清除实时曲线')
        self.clear_btn.clicked.connect(self.clear)
        ctrl.addWidget(self.clear_btn)
        layout.addLayout(ctrl)

        self.setLayout(layout)
        self.t0 = time.time()
        self.time_data = []
        self.intensity_data = []
        self.max_points = 3000

    def add_point(self, intensity):
        t = time.time() - self.t0
        self.time_data.append(t)
        self.intensity_data.append(float(intensity))
        if len(self.time_data) > self.max_points:
            self.time_data = self.time_data[-self.max_points:]
            self.intensity_data = self.intensity_data[-self.max_points:]
        self.curve.setData(self.time_data, self.intensity_data)
        self.latest_label.setText(f'最新强度: {float(intensity):.3f}')

    def clear(self):
        self.t0 = time.time()
        self.time_data.clear()
        self.intensity_data.clear()
        self.curve.setData([], [])
        self.latest_label.setText('最新强度: --')


    def has_data(self):
        return bool(self.time_data)

    def export_csv(self, path):
        with open(path, 'w', encoding='utf-8-sig') as handle:
            handle.write('time_s,intensity_khz\n')
            for t, intensity in zip(self.time_data, self.intensity_data):
                handle.write(f'{float(t):.12g},{float(intensity):.12g}\n')


class Plot2D(QWidget):
    """2D 模式：选两个通道作X/Y轴，灰度热图实时上色"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部：轴选择 + 范围 + 分辨率
        cfg = QGridLayout()
        cfg.addWidget(QLabel('X轴通道:'), 0, 0)
        self.x_combo = QComboBox()
        self.x_combo.addItems([f'通道{i}' for i in range(4)])
        self.x_combo.setCurrentIndex(0)
        cfg.addWidget(self.x_combo, 0, 1)

        self.x_range_label = QLabel('范围(mm):')
        cfg.addWidget(self.x_range_label, 0, 2)
        self.x_min = make_spin(-1.0)
        self.x_max = make_spin(1.0)
        cfg.addWidget(self.x_min, 0, 3)
        cfg.addWidget(self.x_max, 0, 4)

        cfg.addWidget(QLabel('Y轴通道:'), 1, 0)
        self.y_combo = QComboBox()
        self.y_combo.addItems([f'通道{i}' for i in range(4)])
        self.y_combo.setCurrentIndex(1)
        cfg.addWidget(self.y_combo, 1, 1)

        self.y_range_label = QLabel('范围(mm):')
        cfg.addWidget(self.y_range_label, 1, 2)
        self.y_min = make_spin(-1.0)
        self.y_max = make_spin(1.0)
        cfg.addWidget(self.y_min, 1, 3)
        cfg.addWidget(self.y_max, 1, 4)

        cfg.addWidget(QLabel('X像素:'), 0, 5)
        self.grid_x = QSpinBox()
        self.grid_x.setRange(2, 1000)
        self.grid_x.setSingleStep(10)
        self.grid_x.setValue(80)
        self.grid_x.setFixedWidth(70)
        cfg.addWidget(self.grid_x, 0, 6)

        cfg.addWidget(QLabel('Y像素:'), 0, 7)
        self.grid_y = QSpinBox()
        self.grid_y.setRange(2, 1000)
        self.grid_y.setSingleStep(10)
        self.grid_y.setValue(80)
        self.grid_y.setFixedWidth(70)
        cfg.addWidget(self.grid_y, 0, 8)

        self.scan_speed_label = QLabel('扫描速度(mm/s):')
        cfg.addWidget(self.scan_speed_label, 1, 5)
        self.scan_speed_2d = make_spin(1.0, lo=0.001, hi=100.0, dec=3,
                                       step=0.1, width=70)
        cfg.addWidget(self.scan_speed_2d, 1, 6)

        layout.addLayout(cfg)

        # 中间：热图
        plot_box = pg.GraphicsLayoutWidget()
        self.view = plot_box.addPlot()
        self.view.setLabel('left', 'Y 位置', units='mm')
        self.view.setLabel('bottom', 'X 位置', units='mm')
        self.view.setAspectLocked(False)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)

        # 灰度色表
        self.cmap = pg.colormap.get('CET-L1')  # 灰度
        self.img_item.setLookupTable(self.cmap.getLookupTable())

        # colorbar
        self.colorbar = pg.ColorBarItem(values=(0, 1), colorMap=self.cmap,
                                        label='强度')
        self.colorbar.setImageItem(self.img_item, insert_in=self.view)

        layout.addWidget(plot_box, 1)

        # 底部：清除 + 保存
        ctrl = QHBoxLayout()
        self.clear_btn = QPushButton('清除热图')
        self.clear_btn.clicked.connect(self.clear)
        ctrl.addWidget(self.clear_btn)
        self.auto_level = QCheckBox('自动调节亮度范围')
        self.auto_level.setChecked(True)
        ctrl.addWidget(self.auto_level)
        self.export_image_btn = QPushButton('导出图片')
        self.export_image_btn.clicked.connect(self.export_image)
        ctrl.addWidget(self.export_image_btn)
        self.export_data_btn = QPushButton('导出数据')
        self.export_data_btn.clicked.connect(self.export_data)
        ctrl.addWidget(self.export_data_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.setLayout(layout)

        # 数据缓冲：sum/count 累计所有落入像素的样本，image 为均值。
        self.image = None
        self.sum_image = None
        self.weight_image = None
        self.count = None
        self.source = None
        self._last_render_time = 0.0
        self._init_image()

        for widget in (self.x_combo, self.y_combo, self.x_min, self.x_max,
                       self.y_min, self.y_max, self.grid_x, self.grid_y):
            if hasattr(widget, 'valueChanged'):
                widget.valueChanged.connect(lambda _=None: self.clear())
            else:
                widget.currentIndexChanged.connect(lambda _=None: self.clear())
        self.x_combo.currentIndexChanged.connect(lambda _=None: self.update_axis_labels())
        self.y_combo.currentIndexChanged.connect(lambda _=None: self.update_axis_labels())
        self.update_axis_labels()

    def update_axis_labels(self):
        x_ch = self.x_combo.currentIndex()
        y_ch = self.y_combo.currentIndex()
        self.x_range_label.setText(f'范围({CHANNEL_UNITS[x_ch]}):')
        self.y_range_label.setText(f'范围({CHANNEL_UNITS[y_ch]}):')
        if CHANNEL_SPEED_UNITS[x_ch] == CHANNEL_SPEED_UNITS[y_ch]:
            speed_unit = CHANNEL_SPEED_UNITS[x_ch]
        else:
            speed_unit = f'{CHANNEL_SPEED_UNITS[x_ch]} / {CHANNEL_SPEED_UNITS[y_ch]}'
        self.scan_speed_label.setText(f'扫描速度({speed_unit}):')
        self.view.setLabel('bottom', f'X {CHANNEL_NAMES[x_ch]}',
                           units=CHANNEL_UNITS[x_ch])
        self.view.setLabel('left', f'Y {CHANNEL_NAMES[y_ch]}',
                           units=CHANNEL_UNITS[y_ch])

    def _init_image(self):
        nx = int(self.grid_x.value())
        ny = int(self.grid_y.value())
        self.image = np.full((ny, nx), np.nan, dtype=np.float64)
        self.sum_image = np.zeros((ny, nx), dtype=np.float64)
        self.weight_image = np.zeros((ny, nx), dtype=np.float64)
        self.count = np.zeros((ny, nx), dtype=np.int32)
        self.source = np.zeros((ny, nx), dtype=np.int8)
        self._render()

    def get_axes(self):
        """返回 (x_channel, y_channel, x_min, x_max, y_min, y_max, nx, ny)"""
        return (self.x_combo.currentIndex(),
                self.y_combo.currentIndex(),
                self.x_min.value(), self.x_max.value(),
                self.y_min.value(), self.y_max.value(),
                int(self.grid_x.value()), int(self.grid_y.value()))

    def _accumulate_pixel(self, ix, iy, intensity, weight=1.0):
        if weight <= 0:
            return
        self.sum_image[iy, ix] += float(intensity) * float(weight)
        self.weight_image[iy, ix] += float(weight)
        self.count[iy, ix] += 1
        self.image[iy, ix] = (
            self.sum_image[iy, ix] / self.weight_image[iy, ix])
        self.source[iy, ix] = 1

    def add_point(self, x, y, intensity, *, render=True):
        """根据(x,y)位置把intensity累计到对应像素，像素值为加权均值。"""
        if self.image is None:
            return
        _, _, xmin, xmax, ymin, ymax, nx, ny = self.get_axes()
        if xmax <= xmin or ymax <= ymin:
            return
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            return
        ix = min(max(int((x - xmin) / (xmax - xmin) * nx), 0), nx - 1)
        iy = min(max(int((y - ymin) / (ymax - ymin) * ny), 0), ny - 1)
        if 0 <= ix < nx and 0 <= iy < ny:
            self._accumulate_pixel(ix, iy, intensity, weight=1.0)
            now = time.time()
            if render and now - self._last_render_time >= 0.2:
                self._render()
                self._last_render_time = now

    def add_segment(self, x0, y0, intensity0, x1, y1, intensity1):
        """Distribute a measured motion segment by pixel-overlap weighting."""
        if self.image is None:
            return
        _, _, xmin, xmax, ymin, ymax, nx, ny = self.get_axes()
        if xmax <= xmin or ymax <= ymin:
            return
        if not (np.isfinite(x0) and np.isfinite(y0) and
                np.isfinite(x1) and np.isfinite(y1)):
            return

        dx = x1 - x0
        dy = y1 - y0
        if abs(dx) < 1e-15 and abs(dy) < 1e-15:
            self.add_point(x1, y1, intensity1, render=False)
            return

        # For raster scans the long axis dominates. Split exactly by the
        # dominant pixel coordinate so uneven stage velocity does not create
        # missed or over-weighted pixels.
        px0 = (x0 - xmin) / (xmax - xmin) * nx
        px1 = (x1 - xmin) / (xmax - xmin) * nx
        py0 = (y0 - ymin) / (ymax - ymin) * ny
        py1 = (y1 - ymin) / (ymax - ymin) * ny
        use_x = abs(px1 - px0) >= abs(py1 - py0)

        if use_x and abs(dx) >= 1e-15:
            lo = max(min(x0, x1), xmin)
            hi = min(max(x0, x1), xmax)
            if hi <= lo:
                return
            ix0 = max(int((lo - xmin) / (xmax - xmin) * nx), 0)
            ix1 = min(int((hi - xmin) / (xmax - xmin) * nx), nx - 1)
            for ix in range(ix0, ix1 + 1):
                left = xmin + ix * (xmax - xmin) / nx
                right = xmin + (ix + 1) * (xmax - xmin) / nx
                seg_lo = max(lo, left)
                seg_hi = min(hi, right)
                if seg_hi <= seg_lo:
                    continue
                mid_x = 0.5 * (seg_lo + seg_hi)
                t = (mid_x - x0) / dx
                if t < 0.0 or t > 1.0:
                    continue
                mid_y = y0 + dy * t
                if not (ymin <= mid_y <= ymax):
                    continue
                iy = min(max(int((mid_y - ymin) / (ymax - ymin) * ny), 0), ny - 1)
                value = intensity0 + (intensity1 - intensity0) * t
                self._accumulate_pixel(ix, iy, value, weight=(seg_hi - seg_lo))
        elif abs(dy) >= 1e-15:
            lo = max(min(y0, y1), ymin)
            hi = min(max(y0, y1), ymax)
            if hi <= lo:
                return
            iy0 = max(int((lo - ymin) / (ymax - ymin) * ny), 0)
            iy1 = min(int((hi - ymin) / (ymax - ymin) * ny), ny - 1)
            for iy in range(iy0, iy1 + 1):
                bottom = ymin + iy * (ymax - ymin) / ny
                top = ymin + (iy + 1) * (ymax - ymin) / ny
                seg_lo = max(lo, bottom)
                seg_hi = min(hi, top)
                if seg_hi <= seg_lo:
                    continue
                mid_y = 0.5 * (seg_lo + seg_hi)
                t = (mid_y - y0) / dy
                if t < 0.0 or t > 1.0:
                    continue
                mid_x = x0 + dx * t
                if not (xmin <= mid_x <= xmax):
                    continue
                ix = min(max(int((mid_x - xmin) / (xmax - xmin) * nx), 0), nx - 1)
                value = intensity0 + (intensity1 - intensity0) * t
                self._accumulate_pixel(ix, iy, value, weight=(seg_hi - seg_lo))
        self._render()
        self._last_render_time = time.time()

    def finalize_row(self):
        """一行长轴扫描结束后刷新热图，显示该行各像素平均值。"""
        self._render()

    def add_row_time_samples(self, y, x_start, x_end, t_start, t_end, samples):
        """Map one completed long-axis sweep into every X pixel by time."""
        if self.image is None or not samples or t_end <= t_start:
            return
        _, _, xmin, xmax, ymin, ymax, nx, _ = self.get_axes()
        if xmax <= xmin or ymax <= ymin or not (ymin <= y <= ymax):
            return

        ordered = sorted(samples, key=lambda item: item[0])
        sample_t = np.array([item[0] for item in ordered], dtype=np.float64)
        sample_v = np.array([item[1] for item in ordered], dtype=np.float64)
        valid = np.isfinite(sample_t) & np.isfinite(sample_v)
        sample_t = sample_t[valid]
        sample_v = sample_v[valid]
        if sample_t.size == 0:
            return

        # Convert each X pixel center into the corresponding time in this sweep.
        x_centers = xmin + (np.arange(nx) + 0.5) * (xmax - xmin) / nx
        if abs(x_end - x_start) < 1e-15:
            return
        frac = (x_centers - x_start) / (x_end - x_start)
        pixel_t = t_start + frac * (t_end - t_start)

        in_sweep = ((frac >= 0.0) & (frac <= 1.0) &
                    (x_centers >= min(x_start, x_end)) &
                    (x_centers <= max(x_start, x_end)))
        if not in_sweep.any():
            return

        # Average all samples whose mapped time falls inside each pixel interval.
        edges_frac = (np.arange(nx + 1) / nx)
        if x_end < x_start:
            edges_frac = 1.0 - edges_frac
        edge_t = t_start + edges_frac * (t_end - t_start)
        low_edges = np.minimum(edge_t[:-1], edge_t[1:])
        high_edges = np.maximum(edge_t[:-1], edge_t[1:])

        for ix, x in enumerate(x_centers):
            if not in_sweep[ix]:
                continue
            inside = ((sample_t >= low_edges[ix]) &
                      (sample_t < high_edges[ix]))
            if inside.any():
                value = float(np.mean(sample_v[inside]))
            else:
                value = float(np.interp(pixel_t[ix], sample_t, sample_v))
            self.add_point(float(x), float(y), value, render=False)
        self._render()
        self._last_render_time = time.time()

    def fill_missing_pixels(self):
        """No-op kept for compatibility; unmeasured pixels remain empty."""
        return

    def _render(self):
        if self.image is None:
            return
        # 未访问的格子保持 NaN，导出数据时也会标记为空。
        valid = ~np.isnan(self.image)
        if valid.any():
            display = self.image.copy()
            if self.auto_level.isChecked():
                vmin = float(np.nanmin(self.image))
                vmax = float(np.nanmax(self.image))
                if vmax <= vmin:
                    vmax = vmin + 1.0
                display[~valid] = np.nan
                self.img_item.setImage(display.T, levels=(vmin, vmax),
                                       autoLevels=False)
                self.colorbar.setLevels((vmin, vmax))
            else:
                display[~valid] = np.nan
                self.img_item.setImage(display.T, autoLevels=False)
        else:
            self.img_item.setImage(np.zeros_like(self.image).T,
                                   autoLevels=False)

        # 设置坐标范围
        _, _, xmin, xmax, ymin, ymax, _, _ = self.get_axes()
        self.img_item.setRect(pg.QtCore.QRectF(
            xmin, ymin, xmax - xmin, ymax - ymin))

    def clear(self):
        self._init_image()

    def has_data(self):
        return self.image is not None and np.isfinite(self.image).any()

    def export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出热图图片', 'heatmap.png',
            'PNG图片 (*.png);;TIFF图片 (*.tif);;所有文件 (*)')
        if not path:
            return
        self.export_image_to_path(path)

    def export_image_to_path(self, path):
        exporter = pg.exporters.ImageExporter(self.view)
        exporter.export(path)

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出热图数据', 'heatmap_data.csv',
            'CSV数据 (*.csv);;NumPy数组 (*.npz);;所有文件 (*)')
        if not path:
            return
        self.export_data_to_path(path)

    def export_data_to_path(self, path):
        _, _, xmin, xmax, ymin, ymax, nx, ny = self.get_axes()
        x_centers = xmin + (np.arange(nx) + 0.5) * (xmax - xmin) / nx
        y_centers = ymin + (np.arange(ny) + 0.5) * (ymax - ymin) / ny
        if path.lower().endswith('.npz'):
            np.savez(
                path,
                intensity=self.image,
                sample_count=self.count,
                sample_weight=self.weight_image,
                source=self.source,
                x_centers=x_centers,
                y_centers=y_centers,
                x_range=np.array([xmin, xmax]),
                y_range=np.array([ymin, ymax]),
            )
            return
        with open(path, 'w', encoding='utf-8-sig') as handle:
            handle.write('ix,iy,x_center,y_center,intensity_khz,sample_count,sample_weight,source\n')
            for iy, y in enumerate(y_centers):
                for ix, x in enumerate(x_centers):
                    c = int(self.count[iy, ix])
                    value = '' if c == 0 else f'{self.image[iy, ix]:.12g}'
                    weight = f'{self.weight_image[iy, ix]:.12g}'
                    source = 'measured' if self.source[iy, ix] == 1 else 'empty'
                    handle.write(
                        f'{ix},{iy},{x:.12g},{y:.12g},{value},{c},{weight},{source}\n')


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('多通道位移台 + ARTIQ 控制系统')
        self.setGeometry(80, 60, 1500, 900)

        self.controller = None
        self.data_reader = ARTIQDataReader(mode='sipyco')
        self.data_connected = False
        self.last_intensity = None
        self.settings = QSettings('lab-artiq-experiments', 'multi-stage-gui')

        # 扫描状态
        self.scan_mode = '1D'  # '1D' 或 '2D'
        self.scanning = False
        self.scan_direction = [1] * 4  # 1D每个通道方向
        self._last_manual_plot_pos = [None] * 4
        self._1d_state = None
        # 2D光栅扫描状态
        self._2d_state = None  # dict: x_ch, y_ch, x_targets, y_targets, ix, iy, dir
        self._last_error_poll = 0.0
        self.latest_errors = None

        self.init_ui()
        self.setup_timers()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ======== 顶部连接栏 ========
        top = QHBoxLayout()

        top.addWidget(QLabel('COM口:'))
        self.port_input = QLineEdit('COM7')
        self.port_input.setFixedWidth(100)
        top.addWidget(self.port_input)

        self.connect_btn = QPushButton('连接')
        self.connect_btn.clicked.connect(self.on_connect)
        top.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton('断开')
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.disconnect_btn.setEnabled(False)
        top.addWidget(self.disconnect_btn)

        top.addWidget(QLabel('  |  扫描模式:'))
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItems(['1D 扫描 (强度 vs 位置)',
                                       '2D 扫描 (灰度热图)'])
        self.scan_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        top.addWidget(self.scan_mode_combo)

        self.start_scan_btn = QPushButton('开始扫描')
        self.start_scan_btn.clicked.connect(self.on_start_scan)
        self.start_scan_btn.setEnabled(False)
        top.addWidget(self.start_scan_btn)

        self.stop_scan_btn = QPushButton('停止扫描')
        self.stop_scan_btn.clicked.connect(self.on_stop_scan)
        self.stop_scan_btn.setEnabled(False)
        top.addWidget(self.stop_scan_btn)

        self.estop_btn = QPushButton('紧急停止')
        self.estop_btn.setStyleSheet('background-color:#cc3333;color:white;'
                                     'font-weight:bold;')
        self.estop_btn.clicked.connect(self.on_estop)
        top.addWidget(self.estop_btn)

        self.clear_error_btn = QPushButton('清除/复位Error')
        self.clear_error_btn.clicked.connect(self.on_clear_error)
        self.clear_error_btn.setEnabled(False)
        top.addWidget(self.clear_error_btn)

        top.addStretch()
        self.error_summary_label = QLabel('Error: --')
        self.error_summary_label.setStyleSheet('color:#aaa;font-weight:bold;')
        top.addWidget(self.error_summary_label)
        self.status_label = QLabel('未连接')
        self.status_label.setStyleSheet('color:#aaa;')
        top.addWidget(self.status_label)
        root.addLayout(top)

        # ======== ARTIQ 数据连接栏 ========
        data_row = QHBoxLayout()
        data_row.addWidget(QLabel('ARTIQ数据:'))

        self.data_mode_combo = QComboBox()
        self.data_mode_combo.addItems(['sipyco', 'simulated', 'hdf5'])
        self.data_mode_combo.setCurrentText('sipyco')
        self.data_mode_combo.currentTextChanged.connect(self.on_data_mode_changed)
        data_row.addWidget(self.data_mode_combo)

        data_row.addWidget(QLabel('Host:'))
        self.artiq_host_input = QLineEdit('::1')
        self.artiq_host_input.setFixedWidth(110)
        data_row.addWidget(self.artiq_host_input)

        data_row.addWidget(QLabel('Port:'))
        self.artiq_port_input = QLineEdit('3251')
        self.artiq_port_input.setFixedWidth(60)
        data_row.addWidget(self.artiq_port_input)

        data_row.addWidget(QLabel('Dataset:'))
        self.dataset_input = QLineEdit('auto')
        self.dataset_input.setFixedWidth(140)
        data_row.addWidget(self.dataset_input)

        self.connect_artiq_btn = QPushButton('连接ARTIQ')
        self.connect_artiq_btn.clicked.connect(self.on_connect_artiq)
        data_row.addWidget(self.connect_artiq_btn)

        self.disconnect_artiq_btn = QPushButton('断开ARTIQ')
        self.disconnect_artiq_btn.clicked.connect(self.on_disconnect_artiq)
        self.disconnect_artiq_btn.setEnabled(False)
        data_row.addWidget(self.disconnect_artiq_btn)

        self.data_status_label = QLabel('未连接数据源')
        self.data_status_label.setStyleSheet('color:#aaa;')
        data_row.addWidget(self.data_status_label)
        data_row.addStretch()
        root.addLayout(data_row)

        ttl_row = QHBoxLayout()
        ttl_row.addWidget(QLabel('TTL参数:'))

        ttl_row.addWidget(QLabel('门宽(ms):'))
        self.ttl_gate_ms = QDoubleSpinBox()
        self.ttl_gate_ms.setRange(0.001, 10000.0)
        self.ttl_gate_ms.setDecimals(4)
        self.ttl_gate_ms.setSingleStep(0.01)
        self.ttl_gate_ms.setValue(10.0)
        self.ttl_gate_ms.setFixedWidth(90)
        ttl_row.addWidget(self.ttl_gate_ms)

        ttl_row.addWidget(QLabel('每批门数:'))
        self.ttl_subdivisions = QSpinBox()
        self.ttl_subdivisions.setRange(1, 1000000)
        self.ttl_subdivisions.setSingleStep(100)
        self.ttl_subdivisions.setValue(1000)
        self.ttl_subdivisions.setFixedWidth(80)
        ttl_row.addWidget(self.ttl_subdivisions)

        ttl_row.addWidget(QLabel('GUI刷新(ms):'))
        self.gui_refresh_ms = QDoubleSpinBox()
        self.gui_refresh_ms.setRange(10.0, 1000.0)
        self.gui_refresh_ms.setDecimals(1)
        self.gui_refresh_ms.setSingleStep(10.0)
        self.gui_refresh_ms.setValue(20.0)
        self.gui_refresh_ms.setFixedWidth(90)
        ttl_row.addWidget(self.gui_refresh_ms)

        self.apply_ttl_config_btn = QPushButton('应用TTL参数')
        self.apply_ttl_config_btn.clicked.connect(self.on_apply_ttl_config)
        ttl_row.addWidget(self.apply_ttl_config_btn)

        self.ttl_config_status = QLabel('未应用')
        self.ttl_config_status.setStyleSheet('color:#aaa;')
        ttl_row.addWidget(self.ttl_config_status)
        ttl_row.addStretch()
        root.addLayout(ttl_row)

        save_row = QHBoxLayout()
        save_row.addWidget(QLabel('默认保存目录:'))
        default_root = os.path.join(
            os.path.expanduser('~'), 'Documents', 'multi_stage_gui_data')
        self.save_root_input = QLineEdit(
            self.settings.value('save/root', default_root, type=str))
        self.save_root_input.setMinimumWidth(360)
        save_row.addWidget(self.save_root_input, 1)

        self.choose_save_root_btn = QPushButton('选择文件夹')
        self.choose_save_root_btn.clicked.connect(self.on_choose_save_root)
        save_row.addWidget(self.choose_save_root_btn)

        save_row.addWidget(QLabel('文件名后缀:'))
        self.save_tag_input = QLineEdit(
            self.settings.value('save/tag', 'scan', type=str))
        self.save_tag_input.setFixedWidth(160)
        save_row.addWidget(self.save_tag_input)

        self.save_all_btn = QPushButton('一键保存数据')
        self.save_all_btn.clicked.connect(self.on_save_all_data)
        save_row.addWidget(self.save_all_btn)

        self.save_status_label = QLabel('未保存')
        self.save_status_label.setStyleSheet('color:#aaa;')
        save_row.addWidget(self.save_status_label)
        root.addLayout(save_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # ======== 主体：左4通道(2x2) + 右绘图区(tab) ========
        body = QHBoxLayout()

        # 左：2x2 通道控制
        ch_grid = QGridLayout()
        ch_grid.setSpacing(6)
        self.channel_panels = []
        for i in range(4):
            panel = ChannelPanel(i)
            self.channel_panels.append(panel)
            ch_grid.addWidget(panel, i // 2, i % 2)
        ch_widget = QWidget()
        ch_widget.setLayout(ch_grid)
        ch_widget.setFixedWidth(640)
        body.addWidget(ch_widget)

        # 右：绘图标签页
        self.plot_tabs = QTabWidget()
        self.plot_live = PlotLive()
        self.plot_1d = Plot1D()
        self.plot_2d = Plot2D()
        self.plot_tabs.addTab(self.plot_live, '实时信号')
        self.plot_tabs.addTab(self.plot_1d, '1D 曲线')
        self.plot_tabs.addTab(self.plot_2d, '2D 热图')
        self.plot_tabs.currentChanged.connect(self.on_tab_changed)
        body.addWidget(self.plot_tabs, 1)

        root.addLayout(body, 1)

    def on_choose_save_root(self):
        current = self.save_root_input.text().strip()
        if not current:
            current = os.path.expanduser('~')
        path = QFileDialog.getExistingDirectory(
            self, '选择默认保存目录', current)
        if not path:
            return
        self.save_root_input.setText(path)
        self.settings.setValue('save/root', path)

    def _safe_save_tag(self):
        tag = self.save_tag_input.text().strip() or 'scan'
        tag = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', tag)
        tag = re.sub(r'\s+', '_', tag).strip(' ._')
        return tag or 'scan'

    def _make_save_dir_and_base(self):
        root = self.save_root_input.text().strip()
        if not root:
            root = os.path.join(
                os.path.expanduser('~'), 'Documents', 'multi_stage_gui_data')
            self.save_root_input.setText(root)
        now = datetime.now()
        date_day = now.strftime('%Y%m%d')
        save_dir = os.path.join(
            root, now.strftime('%Y'), now.strftime('%Y%m'), date_day)
        os.makedirs(save_dir, exist_ok=True)
        tag = self._safe_save_tag()
        self.save_tag_input.setText(tag)
        self.settings.setValue('save/root', root)
        self.settings.setValue('save/tag', tag)
        return save_dir, f'{date_day}-{tag}'

    def on_save_all_data(self):
        try:
            save_dir, base_name = self._make_save_dir_and_base()
            saved = []

            if self.plot_live.has_data():
                path = os.path.join(save_dir, f'{base_name}_live.csv')
                self.plot_live.export_csv(path)
                saved.append(path)

            if self.plot_1d.has_data():
                path = os.path.join(save_dir, f'{base_name}_1d.csv')
                self.plot_1d.export_csv(path)
                saved.append(path)

            if self.plot_2d.has_data():
                data_path = os.path.join(save_dir, f'{base_name}_2d.csv')
                self.plot_2d.export_data_to_path(data_path)
                saved.append(data_path)
                image_path = os.path.join(save_dir, f'{base_name}_2d.png')
                self.plot_2d.export_image_to_path(image_path)
                saved.append(image_path)

            if not saved:
                self.save_status_label.setText('没有可保存的数据')
                self.save_status_label.setStyleSheet('color:#ffaa66;')
                return

            self.save_status_label.setText(
                f'已保存 {len(saved)} 个文件到 {save_dir}')
            self.save_status_label.setStyleSheet('color:#66dd66;')
        except Exception as exc:
            self.save_status_label.setText(f'保存失败: {exc}')
            self.save_status_label.setStyleSheet('color:#ff6666;')

    def setup_timers(self):
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_all)
        self.update_timer.start(100)

        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scan_step)

    # ------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------
    def on_connect(self):
        port = self.port_input.text().strip()

        simulation = port.lower() in ('sim', 'simulation', 'mock')
        self.controller = NewtonMS4Controller(port=port, simulation=simulation)

        if self.controller.connect():
            label = '模拟位移台' if simulation else port
            self.status_label.setText(f'已连接: {label}')
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_scan_btn.setEnabled(True)
            self.clear_error_btn.setEnabled(True)
            for p in self.channel_panels:
                p.controller = self.controller
            if simulation and not self.data_connected:
                self.data_mode_combo.setCurrentText('simulated')
                self.on_connect_artiq()
        else:
            self.status_label.setText('连接失败')

    def on_disconnect(self):
        self.on_stop_scan()
        if self.controller:
            self.controller.disconnect()
            self.controller = None
        for p in self.channel_panels:
            p.controller = None
        self.status_label.setText('已断开')
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(False)
        self.clear_error_btn.setEnabled(False)
        self.latest_errors = None
        self.update_error_display(None)

    def update_error_display(self, errors):
        if errors is None:
            self.error_summary_label.setText('Error: --')
            self.error_summary_label.setStyleSheet('color:#aaa;font-weight:bold;')
            for panel in self.channel_panels:
                panel.update_error(None)
            return

        has_error = any(code not in (None, 0) for code in errors)
        text = ', '.join('--' if code is None else str(int(code))
                         for code in errors)
        self.error_summary_label.setText(f'Error: {text}')
        color = '#ff5555' if has_error else '#66dd66'
        self.error_summary_label.setStyleSheet(
            f'color:{color};font-weight:bold;')
        for panel, code in zip(self.channel_panels, errors):
            panel.update_error(code)

    def poll_error_status(self, force=False):
        if not self.controller or not self.controller.connected:
            return
        now = time.time()
        if not force and now - self._last_error_poll < 1.0:
            return
        self._last_error_poll = now
        errors = self.controller.get_error_status()
        if errors is not None:
            self.latest_errors = errors
            self.update_error_display(errors)

    def on_clear_error(self):
        if not self.controller or not self.controller.connected:
            return
        self.on_stop_scan()
        ok = self.controller.clear_error()
        if ok:
            self.status_label.setText('已发送清除/复位Error')
            self._last_error_poll = 0.0
            self.poll_error_status(force=True)
        else:
            self.status_label.setText('清除/复位Error失败')

    # ------------------------------------------------------------
    # ARTIQ 数据源
    # ------------------------------------------------------------
    def on_data_mode_changed(self, mode):
        is_sipyco = mode == 'sipyco'
        self.artiq_host_input.setEnabled(is_sipyco)
        self.artiq_port_input.setEnabled(is_sipyco)
        if self.data_connected:
            self.on_disconnect_artiq()

    def on_connect_artiq(self):
        mode = self.data_mode_combo.currentText()
        dataset_name = self.dataset_input.text().strip() or 'auto'
        port = 3251
        if mode == 'sipyco':
            try:
                port = int(self.artiq_port_input.text().strip() or '3251')
            except ValueError:
                self.data_status_label.setText('ARTIQ端口必须是数字')
                return

        self.data_reader.configure(
            mode=mode,
            master_host=self.artiq_host_input.text().strip() or '::1',
            master_port=port,
            dataset_name=dataset_name,
        )
        if self.data_reader.connect():
            self.data_connected = True
            self.connect_artiq_btn.setEnabled(False)
            self.disconnect_artiq_btn.setEnabled(True)
            self.data_status_label.setText(f'数据源已连接: {mode}')
            if mode == 'sipyco':
                self.on_apply_ttl_config()
        else:
            self.data_connected = False
            msg = self.data_reader.last_error or '数据源连接失败'
            self.data_status_label.setText(msg)

    def on_disconnect_artiq(self):
        self.data_reader.disconnect()
        self.data_connected = False
        self.connect_artiq_btn.setEnabled(True)
        self.disconnect_artiq_btn.setEnabled(False)
        self.data_status_label.setText('数据源已断开')

    def on_apply_ttl_config(self):
        gate_time = self.ttl_gate_ms.value() / 1000.0
        gates_per_batch = self.ttl_subdivisions.value()
        ok = self.data_reader.set_ttl_config(
            gate_time=gate_time,
            gate_subdivisions=gates_per_batch,
        )
        if ok:
            self.update_timer.setInterval(max(10, int(self.gui_refresh_ms.value())))
            effective_gate_ms = gate_time * gates_per_batch * 1000.0
            self.ttl_config_status.setText(
                f'已应用: 门宽 {gate_time * 1e6:.3f} us, 每批 {effective_gate_ms:.3f} ms')
            self.ttl_config_status.setStyleSheet('color:#66dd66;')
        else:
            msg = self.data_reader.last_error or '写入TTL参数失败'
            self.ttl_config_status.setText(msg)
            self.ttl_config_status.setStyleSheet('color:#ff5555;')

    # ------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------
    def on_mode_changed(self, idx):
        self.scan_mode = '1D' if idx == 0 else '2D'
        self.plot_tabs.setCurrentIndex(idx + 1)

    def on_tab_changed(self, idx):
        if idx == 0:
            return
        # 用户点1D/2D tab时同步下拉框
        self.scan_mode_combo.blockSignals(True)
        self.scan_mode_combo.setCurrentIndex(idx - 1)
        self.scan_mode_combo.blockSignals(False)
        self.scan_mode = '1D' if idx == 1 else '2D'

    # ------------------------------------------------------------
    # 扫描控制
    # ------------------------------------------------------------
    def on_start_scan(self):
        if not self.controller or not self.controller.connected:
            return

        self.scanning = True
        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        if not self.data_connected:
            self.data_status_label.setText('未连接数据源：只移动，不记录强度')

        if self.scan_mode == '1D':
            enabled = [i for i, p in enumerate(self.channel_panels)
                       if p.scan_enable.isChecked()]
            if not enabled:
                self.status_label.setText('请至少启用一个1D扫描通道')
                self.scanning = False
                self.start_scan_btn.setEnabled(True)
                self.stop_scan_btn.setEnabled(False)
                return
            self.plot_tabs.setCurrentIndex(1)
            self.plot_1d.clear()
            self._1d_state = {
                'enabled': enabled,
                'phase': 'goto_start',
            }
            self.status_label.setText('1D 扫描：移动到起点...')
            for i in enabled:
                p = self.channel_panels[i]
                self.scan_direction[i] = 1
                self.controller.move_to(i, p.scan_start.value(),
                                        speed=p.scan_speed.value())
        else:
            # 2D：初始化光栅扫描状态
            x_ch, y_ch, xmin, xmax, ymin, ymax, nx, ny = self.plot_2d.get_axes()
            if x_ch == y_ch:
                self.status_label.setText('X/Y必须是不同通道')
                self.scanning = False
                self.start_scan_btn.setEnabled(True)
                self.stop_scan_btn.setEnabled(False)
                return
            if xmax <= xmin or ymax <= ymin:
                self.status_label.setText('2D扫描范围设置错误')
                self.scanning = False
                self.start_scan_btn.setEnabled(True)
                self.stop_scan_btn.setEnabled(False)
                return
            self.plot_tabs.setCurrentIndex(2)
            self.plot_2d.clear()
            speed = self.plot_2d.scan_speed_2d.value()
            positions = self.controller.get_all_positions()
            if positions is not None:
                x0 = xmin if positions[x_ch] is None else positions[x_ch]
                y0 = ymin if positions[y_ch] is None else positions[y_ch]
                dx0 = abs(x0 - xmin)
                dy0 = abs(y0 - ymin)
                goto_timeout = max(dx0, dy0) / max(speed, 1e-6) + 3.0
            else:
                goto_timeout = 10.0
            self._2d_state = {
                'x_ch': x_ch, 'y_ch': y_ch,
                'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax,
                'nx': nx, 'ny': ny, 'speed': speed,
                'iy': 0, 'x_dir': 1,
                'current_x_target': xmin,
                'current_y_target': ymin,
                'goto_start_time': time.time(),
                'goto_timeout': max(goto_timeout, 3.0),
                'last_status_update': 0.0,
                'phase': 'goto_start',  # goto_start -> sweep_x -> step_y -> sweep_x ...
            }
            self.status_label.setText('2D 扫描中...')
            # 移动到起点
            self.controller.move_to(x_ch, xmin, speed=speed)
            self.controller.move_to(y_ch, ymin, speed=speed)

        self.scan_timer.start(150)

    def on_stop_scan(self):
        self.scanning = False
        self.scan_timer.stop()
        self._1d_state = None
        self._2d_state = None
        if self.controller and self.controller.connected:
            self.controller.stop_all()
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText('扫描已停止')

    def finish_scan(self, message):
        self.scanning = False
        self.scan_timer.stop()
        self._1d_state = None
        self._2d_state = None
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText(message)

    def on_estop(self):
        self.on_stop_scan()
        if self.controller and self.controller.connected:
            self.controller.stop_all()

    def axis_reached(self, channel, target, positions=None, tol=1e-4):
        """Return True when an axis reports target reached or is close enough."""
        try:
            if self.controller.is_on_target(channel):
                return True
        except Exception:
            pass
        pos = None
        if positions is not None and 0 <= channel < len(positions):
            pos = positions[channel]
        if pos is None:
            try:
                pos = self.controller.get_position(channel)
            except Exception:
                pos = None
        return pos is not None and abs(float(pos) - float(target)) <= tol

    def start_2d_sweep_row(self, st, positions=None, forced=False):
        """Start one long-axis sweep row from the current/known X position."""
        if positions is None:
            positions = self.controller.get_all_positions()
        st['phase'] = 'sweep_x'
        st['last_sample'] = None
        st['row_start_time'] = time.time()
        if positions is not None and positions[st['x_ch']] is not None:
            st['row_start_x'] = positions[st['x_ch']]
        else:
            st['row_start_x'] = st['xmin'] if st['x_dir'] > 0 else st['xmax']
        st['row_y'] = None if positions is None else positions[st['y_ch']]
        target_x = st['xmax'] if st['x_dir'] > 0 else st['xmin']
        st['row_end_x'] = target_x
        st['current_x_target'] = target_x
        self.controller.move_to(st['x_ch'], target_x, speed=st['speed'])
        if forced:
            self.status_label.setText('2D 起点状态等待超时，已从当前位置开始长轴扫描')
        else:
            self.status_label.setText('2D 长轴扫描中...')

    def scan_step(self):
        """扫描步进逻辑（每150ms）"""
        if not self.scanning or not self.controller:
            return

        if self.scan_mode == '1D':
            st = self._1d_state
            if st is None:
                return
            enabled = st['enabled']
            all_on_target = all(self.controller.is_on_target(i) for i in enabled)
            if st['phase'] == 'goto_start' and all_on_target:
                st['phase'] = 'sweep'
                self.status_label.setText('1D 扫描中...')
                for i in enabled:
                    p = self.channel_panels[i]
                    self.controller.move_to(i, p.scan_end.value(),
                                            speed=p.scan_speed.value())
            elif st['phase'] == 'sweep' and all_on_target:
                self.finish_scan('1D 扫描完成')
        else:
            # 2D：光栅扫描（X 行扫，每行结束后 Y 步进一格）
            st = self._2d_state
            if st is None:
                return

            positions = self.controller.get_all_positions()
            x_target = st.get('current_x_target', st['xmin'])
            y_target = st.get('current_y_target', st['ymin'])
            x_on = self.axis_reached(st['x_ch'], x_target, positions)
            y_on = self.axis_reached(st['y_ch'], y_target, positions)

            if st['phase'] == 'goto_start':
                now = time.time()
                timeout = now - st.get('goto_start_time', now) > st.get('goto_timeout', 10.0)
                if x_on and y_on:
                    self.start_2d_sweep_row(st, positions, forced=False)
                elif timeout:
                    self.start_2d_sweep_row(st, positions, forced=True)
                elif now - st.get('last_status_update', 0.0) > 1.0:
                    st['last_status_update'] = now
                    self.status_label.setText(
                        f"2D 等待起点: X={'OK' if x_on else '--'} "
                        f"Y={'OK' if y_on else '--'}")
            elif st['phase'] == 'sweep_x':
                if x_on:
                    self.plot_2d.finalize_row()
                    # 一行扫完，Y 步进
                    st['iy'] += 1
                    if st['iy'] >= st['ny']:
                        # 整个面扫完，单次扫描结束
                        self.finish_scan('2D 扫描完成')
                    else:
                        # Y 移到下一行
                        y_target = (st['ymin'] +
                                    (st['ymax'] - st['ymin']) * st['iy'] /
                                    max(st['ny'] - 1, 1))
                        st['current_y_target'] = y_target
                        self.controller.move_to(st['y_ch'], y_target,
                                                speed=st['speed'])
                        st['x_dir'] *= -1  # 蛇形扫描，下一行反向
                        st['phase'] = 'step_y'
            elif st['phase'] == 'step_y':
                if y_on:
                    st['last_sample'] = None
                    st['row_start_time'] = time.time()
                    st['row_start_x'] = st['xmin'] if st['x_dir'] > 0 else st['xmax']
                    pos = self.controller.get_all_positions()
                    st['row_y'] = None if pos is None else pos[st['y_ch']]
                    target_x = st['xmax'] if st['x_dir'] > 0 else st['xmin']
                    st['row_end_x'] = target_x
                    st['current_x_target'] = target_x
                    self.controller.move_to(st['x_ch'], target_x,
                                            speed=st['speed'])
                    st['phase'] = 'sweep_x'

    # ------------------------------------------------------------
    # 数据更新
    # ------------------------------------------------------------
    def update_all(self):
        positions = None
        if self.controller and self.controller.connected:
            positions = self.controller.get_all_positions()
            if positions is not None:
                for pos, panel in zip(positions, self.channel_panels):
                    panel.update_position(pos)
            self.poll_error_status()

        intensity = None
        if self.data_connected:
            sim_pos = positions
            if (positions is not None and self.scan_mode == '2D' and
                    self._2d_state is not None):
                st = self._2d_state
                sim_pos = [positions[st['x_ch']], positions[st['y_ch']], 0, 0]

            intensity = self.data_reader.read_intensity(sim_pos)
            if intensity is not None:
                self.last_intensity = intensity
                self.plot_live.add_point(intensity)
                src = self.data_reader.last_dataset or self.data_reader.mode
                status = f'强度 {intensity:.3f} ({src})'
                if self.data_reader.last_warning:
                    status = f'{status} | {self.data_reader.last_warning}'
                self.data_status_label.setText(status)
            elif self.data_reader.last_error:
                self.data_status_label.setText(self.data_reader.last_error)

        if positions is None:
            return

        # 扫描中：把同一时刻的位置信息和强度送到对应图像。
        if self.scanning and intensity is not None:
            if self.scan_mode == '1D':
                if (self._1d_state is None or
                        self._1d_state.get('phase') != 'sweep'):
                    return
                for i, p in enumerate(self.channel_panels):
                    if p.scan_enable.isChecked() and positions[i] is not None:
                        self.plot_1d.add_point(i, positions[i], intensity)
            else:
                st = self._2d_state
                if st is not None and st.get('phase') == 'sweep_x':
                    if not self.data_reader.last_is_new_sample:
                        return
                    if self.data_reader.last_status not in ("", "running"):
                        return
                    x_pos = positions[st['x_ch']]
                    y_pos = positions[st['y_ch']]
                    if x_pos is not None and y_pos is not None:
                        last = st.get('last_sample')
                        if last is None:
                            self.plot_2d.add_point(x_pos, y_pos, intensity)
                        else:
                            self.plot_2d.add_segment(
                                last[0], last[1], last[2],
                                x_pos, y_pos, intensity)
                        st['last_sample'] = (x_pos, y_pos, intensity)
        elif intensity is not None and self.plot_tabs.currentIndex() == 1:
            # 手动移动时也允许在 1D 页上记录位置-强度轨迹。
            for i, panel in enumerate(self.channel_panels):
                pos = positions[i]
                if not panel.scan_enable.isChecked() or pos is None:
                    continue
                last_pos = self._last_manual_plot_pos[i]
                if last_pos is None or abs(pos - last_pos) >= 1e-4:
                    self.plot_1d.add_point(i, pos, intensity)
                    self._last_manual_plot_pos[i] = pos

    def closeEvent(self, event):
        self.on_stop_scan()
        if self.controller:
            self.controller.disconnect()
        self.data_reader.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)

    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.AlternateBase, QColor(55, 55, 55))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(60, 60, 60))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(200, 200, 200))
    palette.setColor(QPalette.Link, QColor(150, 150, 150))
    palette.setColor(QPalette.Highlight, QColor(80, 80, 80))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
