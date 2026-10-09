# -*- coding: utf-8 -*-
"""原生 Windows 悬浮岛：圆角裁剪、可中断的形态变化与点击/拖动。"""
import ctypes
import math
import time
import tkinter as tk
from ctypes import wintypes

ISLAND_BG = "#11151b"
ISLAND_PRESSED = "#202733"
ISLAND_TEXT = "#f3f6fa"
ISLAND_MUTED = "#a8b4c4"
ISLAND_FIELD = "#202630"
ISLAND_LINE = "#364150"
PILL_SIZE = (224, 52)
PANEL_SIZE = (460, 650)
PANEL_RADIUS = 28
SPRING_RESPONSE = 0.3


def animations_enabled():
    """跟随 Windows 设置中的动画开关。"""
    try:
        enabled = wintypes.BOOL()
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except (AttributeError, OSError):
        pass
    return True


def work_area(x, y, fallback):
    """使用胶囊所在显示器的工作区，展开不盖住任务栏。"""
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    try:
        u = ctypes.windll.user32
        u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        u.MonitorFromPoint.restype = ctypes.c_void_p
        u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
        monitor = u.MonitorFromPoint(wintypes.POINT(round(x), round(y)), 2)
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        if monitor and u.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return (r.left, r.top, r.right, r.bottom)
    except (AttributeError, OSError):
        pass
    return (0, 0, *fallback)


class IslandWindow(tk.Toplevel):
    """子类提供 _pill 和 _panel，内容只在形态稳定后呈现。"""
    def __init__(self, master):
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=ISLAND_BG)
        self.expanded = False
        self._morph_id = self._focus_id = self._region_id = None
        self._anchor = [0.0, 0.0]
        self._values = [*map(float, PILL_SIZE), 0.0, 0.0, PILL_SIZE[1] / 2]
        self._velocity = [0.0] * 5
        self._target = self._values[:]
        self._spring_start = None
        self._drag_origin = None
        self._drag_moved = False
        self._context_open = False
        self._focus_after_expand = False
        self._dismiss_after_morph = False
        self._last_region = None
        self.reduce_motion = bool(master.t.config.get("overlayReduceMotion", False)) or not animations_enabled()
        self.bind("<Configure>", self._queue_region, add="+")
        self.bind("<FocusOut>", self._queue_focus_check, add="+")

    def initialize_island(self, position):
        self._anchor = list(map(float, position))
        self._clamp_anchor()
        self._values = self._geometry_for(False)
        self._target = self._values[:]
        self._render_geometry()
        self._show_pill()

    def _area(self):
        return work_area(self._anchor[0] + PILL_SIZE[0] / 2, self._anchor[1],
                         (self.winfo_screenwidth(), self.winfo_screenheight()))

    def _clamp_anchor(self):
        left, top, right, bottom = self._area()
        self._anchor[0] = max(left + 8, min(self._anchor[0], right - PILL_SIZE[0] - 8))
        self._anchor[1] = max(top + 8, min(self._anchor[1], bottom - PILL_SIZE[1] - 8))

    def _geometry_for(self, expanded):
        left, top, right, bottom = self._area()
        if not expanded:
            return [*map(float, PILL_SIZE), *self._anchor, PILL_SIZE[1] / 2]
        w, h = min(PANEL_SIZE[0], right - left - 16), min(PANEL_SIZE[1], bottom - top - 16)
        x = self._anchor[0] + (PILL_SIZE[0] - w) / 2
        # 下方放不下时向上展开，保持胶囊的底边位置。
        y = self._anchor[1] if self._anchor[1] + h <= bottom - 8 else self._anchor[1] + PILL_SIZE[1] - h
        return [float(w), float(h), max(left + 8, min(x, right - w - 8)),
                max(top + 8, min(y, bottom - h - 8)), float(PANEL_RADIUS)]

    def show(self, expanded=False):
        self._clamp_anchor()
        self._set_expanded(expanded, animate=False, focus=False)
        self.deiconify()
        self.lift()
        self._queue_region()

    def hide(self):
        self._set_expanded(False, animate=False, focus=False)
        self.withdraw()

    def expand(self, animate=True, focus=True):
        if not self.winfo_viewable():
            self.deiconify()
        self._set_expanded(True, animate=animate, focus=focus)

    def collapse(self, animate=True):
        self._set_expanded(False, animate=animate, focus=False)

    def toggle_expanded(self, animate=True):
        self._set_expanded(not self.expanded, animate=animate, focus=not self.expanded)

    def _cancel(self, name):
        timer = getattr(self, name, None)
        if timer is not None:
            try:
                self.after_cancel(timer)
            except tk.TclError:
                pass
            setattr(self, name, None)

    def _sample_spring(self):
        if self._spring_start is None:
            return
        dt = time.perf_counter() - self._spring_start
        omega = 2 * math.pi / SPRING_RESPONSE
        decay = math.exp(-omega * dt)
        for i, (origin, velocity, target) in enumerate(zip(self._origin, self._initial_velocity, self._target)):
            delta = origin - target
            slope = velocity + omega * delta
            self._values[i] = target + (delta + slope * dt) * decay
            self._velocity[i] = (velocity - omega * slope * dt) * decay

    def _set_expanded(self, expanded, animate, focus):
        self._cancel("_morph_id")
        self.expanded = expanded
        self._focus_after_expand = expanded and focus
        self._dismiss_after_morph = False
        self._target = self._geometry_for(expanded)
        if not animate or self.reduce_motion:
            self._spring_start = None
            self._values = self._target[:]
            self._velocity = [0.0] * 5
            self._render_geometry()
            self._finish_morph()
            return
        # 反向动作从当前展示值和速度继续，禁止从终点重新开始。
        self._panel.place_forget()
        self._show_pill()
        self._origin = self._values[:]
        self._initial_velocity = self._velocity[:]
        self._spring_start = time.perf_counter()
        self._tick_morph()

    def _tick_morph(self):
        self._morph_id = None
        self._sample_spring()
        self._render_geometry()
        settled = all(abs(v - t) < .5 and abs(speed) < 8
                      for v, t, speed in zip(self._values, self._target, self._velocity))
        if settled:
            self._spring_start = None
            self._values = self._target[:]
            self._velocity = [0.0] * 5
            self._render_geometry()
            self._finish_morph()
        else:
            self._morph_id = self.after(16, self._tick_morph)

    def _render_geometry(self):
        w, h, x, y, radius = self._values
        self.geometry("%dx%d+%d+%d" % (round(w), round(h), round(x), round(y)))
        self._pill.place_configure(x=round((w - PILL_SIZE[0]) / 2), y=0)
        self._queue_region()

    def _show_pill(self):
        self._panel.place_forget()
        self._pill.place(x=round((self._values[0] - PILL_SIZE[0]) / 2), y=0,
                         width=PILL_SIZE[0], height=PILL_SIZE[1])

    def _finish_morph(self):
        if self.expanded:
            self._pill.place_forget()
            self._panel.place(x=0, y=0, width=round(self._values[0]), height=round(self._values[1]))
            if self._focus_after_expand:
                self.lift()
                self.txt_in.focus_force()
            elif self._dismiss_after_morph:
                self._queue_focus_check()
        else:
            self._show_pill()

    def _queue_region(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self._region_id is None:
            self._region_id = self.after_idle(self._apply_region)

    def _apply_region(self):
        self._region_id = None
        if not self.winfo_ismapped():
            return
        try:
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            u.GetAncestor.argtypes = [ctypes.c_void_p, wintypes.UINT]
            u.GetAncestor.restype = ctypes.c_void_p
            g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            g.CreateRoundRectRgn.restype = ctypes.c_void_p
            u.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
            g.DeleteObject.argtypes = [ctypes.c_void_p]
            hwnd = u.GetAncestor(self.winfo_id(), 2)
            w, h = self.winfo_width(), self.winfo_height()
            # Tk 首次映射前还没有外层窗口；不能把区域裁到 Tk 子窗口，
            # 否则映射后的内容仍被旧的 1px 区域永久遮住。
            if hwnd == self.winfo_id() or w < 3 or h < 3:
                return
            diameter = round(min(self._values[4] * 2, h))
            signature = (hwnd, w, h, diameter)
            if signature == self._last_region:
                return
            region = g.CreateRoundRectRgn(0, 0, w + 1, h + 1, diameter, diameter)
            if region:
                # SetWindowRgn 自身会发 Configure；相同区域不能反复设置，
                # 否则 idle 队列持续重绘，会饿死 Tk 的内容绘制。
                if u.SetWindowRgn(hwnd, region, True):
                    self._last_region = signature
                else:
                    g.DeleteObject(region)
        except (AttributeError, OSError, tk.TclError):
            pass

    def bind_drag(self, widget, activates=False):
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", lambda e: self._drag_end(e, activates))

    def _drag_start(self, event):
        self._cancel("_morph_id")
        self._spring_start = None
        self._drag_origin = (event.x_root, event.y_root, self._values[:], self._anchor[:])
        self._drag_moved = False
        if not self.expanded:
            for widget in (self._pill, *self._pill.winfo_children()):
                widget.configure(bg=ISLAND_PRESSED)

    def _drag_move(self, event):
        if self._drag_origin is None:
            return
        px, py, values, anchor = self._drag_origin
        dx, dy = event.x_root - px, event.y_root - py
        if not self._drag_moved and math.hypot(dx, dy) < 6:
            return
        self._drag_moved = True
        self._anchor = [anchor[0] + dx, anchor[1] + dy]
        self._values[2:4] = [values[2] + dx, values[3] + dy]
        self._render_geometry()

    def _drag_end(self, event, activates=False):
        if self._drag_origin is None:
            return
        self._drag_origin = None
        for widget in (self._pill, *self._pill.winfo_children()):
            widget.configure(bg=ISLAND_BG)
        if self._drag_moved:
            self._clamp_anchor()
            self._set_expanded(self.expanded, animate=False, focus=False)
            self.master.t.config["overlayIslandPos"] = list(map(round, self._anchor))
            self.master.t.save_config()
        elif activates:
            self.toggle_expanded()
        elif self._values != self._target:
            self._set_expanded(self.expanded, animate=True, focus=False)

    def _queue_focus_check(self, _event=None):
        if _event is not None and self.expanded and self._morph_id:
            self._focus_after_expand = False
            self._dismiss_after_morph = True
        self._cancel("_focus_id")
        self._focus_id = self.after(120, self._check_focus)

    def _check_focus(self):
        self._focus_id = None
        if not self.expanded or self._context_open or self._drag_origin or self._morph_id:
            return
        if self.grab_current() is not None:
            return
        focused = self.focus_get()
        if focused is None or focused.winfo_toplevel() is not self:
            self.collapse()

    def destroy(self):
        for name in ("_morph_id", "_focus_id", "_region_id", "_flash_id"):
            self._cancel(name)
        super().destroy()
