# -*- coding: utf-8 -*-
"""
ui_kit.py  —  界面用的小零件

主窗口和悬浮窗都要用，所以单独放一个文件，避免循环导入。
这里只有画东西的函数，不依赖任何窗口结构。
"""

import math
import sys
from pathlib import Path

# 主色（跟主窗口保持一致）
C_BG = "#f5f7fa"
C_LINE = "#dde4eb"
C_MINE = "#2459a6"      # 我 → 对方
C_PEER = "#08796d"      # 对方 → 我
C_OUT_BG = "#f3f7fb"
C_MUTED = "#596b7d"
C_TEXT = "#203247"
C_SURFACE = "#ffffff"
C_SIDEBAR = "#edf2f7"

# Windows 原生中英文字体，字号以 point 计，跟随系统 DPI。
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_HEAD = ("Microsoft YaHei UI", 13, "bold")
FONT_TEXT = ("Microsoft YaHei UI", 12)
FONT_TITLE = ("Microsoft YaHei UI", 21, "bold")
C_OK = "#15803d"        # 成功/可用
C_BAD = "#b91c1c"       # 失败/不可用


def asset_path(name):
    """源码与 PyInstaller 包内使用同一套静态资源。"""
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "assets" / name


def brand_icon(master, size=32):
    import tkinter as tk
    return tk.PhotoImage(master=master, file=str(asset_path("app-icon-%d.png" % size)))


def apply_app_icon(root):
    """设置主窗口及后续子窗口默认图标，保留 Tk 图像引用。"""
    root._app_icon_images = [brand_icon(root, size) for size in (32, 64)]
    root.iconphoto(True, *root._app_icon_images)
    if sys.platform == "win32":
        root.iconbitmap(default=str(asset_path("app-icon.ico")))


def text_surface(master, text_class=None, **kwargs):
    """有内边距、焦点边框和滚动条的原生编辑区。"""
    import tkinter as tk
    from tkinter import ttk

    bg = kwargs.get("bg", C_SURFACE)
    frame = tk.Frame(master, bg=bg, highlightthickness=1,
                     highlightbackground=C_LINE, bd=0)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    defaults = dict(wrap="word", font=FONT_TEXT, fg=C_TEXT, bg=bg,
                    relief="flat", borderwidth=0, highlightthickness=0,
                    padx=14, pady=12, spacing1=2, spacing3=5,
                    insertbackground=C_MINE, selectbackground="#cfe1f5",
                    selectforeground=C_TEXT, width=1)
    defaults.update(kwargs)
    widget = (text_class or tk.Text)(frame, **defaults)
    widget.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview, takefocus=False)
    scroll.grid(row=0, column=1, sticky="ns", padx=(0, 3), pady=4)
    widget.configure(yscrollcommand=scroll.set)
    widget.bind("<FocusIn>", lambda e: frame.configure(
        highlightbackground=C_MINE), add="+")
    widget.bind("<FocusOut>", lambda e: frame.configure(
        highlightbackground=C_LINE), add="+")
    def move_focus(forward):
        (widget.tk_focusNext() if forward else widget.tk_focusPrev()).focus_set()
        return "break"
    widget.bind("<Tab>", lambda e: move_focus(True))
    widget.bind("<Shift-Tab>", lambda e: move_focus(False))
    widget.bind("<ISO_Left_Tab>", lambda e: move_focus(False))
    return frame, widget

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
    def select_all(_e):
        widget.tag_add("sel", "1.0", "end-1c")
        return "break"
    widget.bind("<Control-a>", select_all)
    widget.bind("<Control-A>", select_all)
    for event in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<Button-2>"):
        widget.bind(event, lambda e: "break")
    return widget
