# -*- coding: utf-8 -*-
"""
ui_kit.py  —  界面用的小零件

主窗口和悬浮窗都要用，所以单独放一个文件，避免循环导入。
这里只有画东西的函数，不依赖任何窗口结构。
"""

import math

# 主色（跟主窗口保持一致）
C_BG = "#f4f5f7"
C_LINE = "#dfe3e8"
C_MINE = "#2563eb"      # 我 → 对方
C_PEER = "#0f9d58"      # 对方 → 我
C_OUT_BG = "#fbfcfe"
C_MUTED = "#8b93a1"
C_OK = "#15803d"        # 成功/可用
C_BAD = "#b91c1c"       # 失败/不可用

# ───────────────────────── 喇叭电平表 ─────────────────────────

# 喇叭轮廓（朝右），30x30 画布内的点
SPEAKER_SHAPE = [(3, 8), (10, 8), (22, 1), (22, 29), (10, 22), (3, 22)]
SPEAKER_W, SPEAKER_H = 30, 30


def clip_poly_below(points, ycut):
    """把多边形裁到 y >= ycut 的部分，返回新的点列。y 轴朝下。

    Canvas 没有裁剪功能，所以蓝色填充那块是这里自己算出来的
    （Sutherland-Hodgman，对着一条水平线裁）。
    """
    out = []
    n = len(points)
    for i in range(n):
        cx, cy = points[i]
        nx, ny = points[(i + 1) % n]
        c_in = cy >= ycut
        n_in = ny >= ycut
        if c_in:
            out.append((cx, cy))
        if c_in != n_in:
            t = (ycut - cy) / float(ny - cy)
            out.append((cx + t * (nx - cx), ycut))
    return out


def norm_level(peak, floor_db=-48.0):
    """把原始振幅换成 0.0-1.0 的显示值。

    必须按 dB 走，不能线性：实测正常说话时麦克风峰值只有 0.02-0.2，
    线性映射到 0-1 后条子只填几个像素，看着像坏的（真踩过这个坑）。
    floor_db 是"显示为空"的门槛，-48 dB 约等于 0.004。
    """
    if peak is None or peak <= 0:
        return 0.0
    db = 20.0 * math.log10(min(1.0, float(peak)))
    if db <= floor_db:
        return 0.0
    return max(0.0, min(1.0, (db - floor_db) / (0.0 - floor_db)))


def draw_level(canvas, v, color, w=SPEAKER_W, h=SPEAKER_H):
    """灰色喇叭打底，彩色按音量从下往上填。v 是 0.0-1.0。"""
    canvas.delete("all")
    canvas.create_polygon(*[q for p in SPEAKER_SHAPE for q in p],
                          fill="#d8dde4", outline="#aeb6c0")
    v = max(0.0, min(1.0, v))
    if v > 0.015:
        part = clip_poly_below(SPEAKER_SHAPE, h - v * h)
        if len(part) >= 3:
            canvas.create_polygon(*[q for p in part for q in p],
                                  fill=color, outline="")


# ───────────────────────── 输入框占位提示 ─────────────────────────

def readonly_text(widget):
    """只读，但允许选中和 Ctrl+C / Ctrl+A。"""
    def on_key(e):
        if (e.state & 0x4) and e.keysym.lower() in ("c", "a"):
            return None
        if e.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                        "Shift_L", "Shift_R", "Control_L", "Control_R", "Escape", "Tab"):
            return None
        return "break"
    widget.bind("<Key>", on_key)
    return widget
