# -*- coding: utf-8 -*-
"""
overlay.py  —  悬浮翻译面板 + 全局快捷键

为什么要有这个：
    主窗口 1240x860，和浏览器并排时太占地方。跟 Claude / GPT 聊天时，
    真正需要的只有「输入 → 译文 → 复制」这三步。

两个东西：
    OverlayPanel    小面板，置顶、可拖、吸边、可调透明度、两栏一键切换
    HotkeyThread    全局快捷键（不抢焦点），Ctrl+Alt+O 显示/隐藏，Ctrl+Alt+T 翻剪贴板

设计上刻意做成"第二个 Lane"：它实现了和主窗口 Lane 一样的一组方法
（get_input / set_input / set_output / set_pair / set_busy /
  set_recording / set_level / refresh_memory + side 属性），
所以主窗口的 translate_lane() 和录音流程可以直接拿来用，不用复制一份逻辑。
"""

import ctypes
import os
import queue
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk, simpledialog, messagebox

from ui_kit import (C_BG, C_LINE, C_MINE, C_MUTED, C_OUT_BG, C_PEER,
                    SPEAKER_H, SPEAKER_W, draw_level, norm_level, readonly_text)

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 10, "bold")

ALPHAS = [1.0, 0.92, 0.85, 0.75]

# ───────────────────────── 全局快捷键 ─────────────────────────

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# 设置界面里可以选的非修饰键（显示名, 虚拟键码）。
# 只放字母 / 数字 / F1-F12 —— 再多也没人用，而且容易和系统键打架。
HOTKEY_KEYS = ([(chr(c), c) for c in range(0x41, 0x5B)]        # A-Z
               + [(str(d), 0x30 + d) for d in range(10)]        # 0-9
               + [("F%d" % i, 0x70 + i - 1) for i in range(1, 13)])

# 默认快捷键。
# 为什么不用 Ctrl+Alt+O / Ctrl+Alt+T：实测这两个已被别的程序占用（错误码 1409）。
# 为什么不用 Ctrl+Shift+O / Ctrl+Shift+T：那两个虽然空着，但浏览器/编辑器都在用
#   （重开标签页、书签管理器），全局注册会把它们从所有程序里抢走。
# Win+Alt+* 相对干净：系统只占了 R / G / PrtScn / B / Enter。
DEFAULT_TOGGLE = (MOD_WIN | MOD_ALT, 0x4F)   # Win+Alt+O  悬浮窗
DEFAULT_CLIP = (MOD_WIN | MOD_ALT, 0x56)     # Win+Alt+V  翻剪贴板


def key_name(mods, vk):
    parts = []
    if mods & MOD_WIN:          # Win 放最前，读起来顺（Win+Alt+O）
        parts.append("Win")
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    parts.append(chr(vk) if 0x41 <= vk <= 0x5A else
                 ("%d" % (vk - 0x30) if 0x30 <= vk <= 0x39 else
                  ("F%d" % (vk - 0x70 + 1) if 0x70 <= vk <= 0x7B else "0x%X" % vk)))
    return "+".join(parts)


class HotkeyThread(threading.Thread):
    """在独立线程里注册全局快捷键。

    为什么单开线程：RegisterHotKey(hwnd=None) 把 WM_HOTKEY 投递到
    **注册它的那个线程**的消息队列。主线程被 tkinter 占着，从里面
    PeekMessage 会把 tk 自己的消息也捞走，所以另起一个线程专职收发。

    命中后往 queue 里丢一个 id，主线程用 after() 轮询取走 ——
    跨线程直接碰 tkinter 控件是不安全的。
    """

    def __init__(self, hotkeys, name="hotkeys"):
        """hotkeys: {id: (修饰键, 虚拟键码, 说明)}"""
        super().__init__(daemon=True, name=name)
        self.hotkeys = hotkeys
        self.fired = queue.Queue()
        self.registered = {}
        self.failed = {}
        self._tid = None
        self._stop = threading.Event()

    # GetLastError 必须用 use_last_error=True 的句柄才取得准，
    # 默认的 ctypes.windll 不捕获 last error（之前在这上面栽过）。
    ERR_ALREADY = 1409

    def run(self):
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self._tid = k.GetCurrentThreadId()

        for hid, (mods, vk, desc) in self.hotkeys.items():
            if u.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self.registered[hid] = desc
            else:
                err = ctypes.get_last_error()
                self.failed[hid] = (desc, err,
                                    "已被其它程序占用" if err == self.ERR_ALREADY
                                    else "注册失败(错误码 %s)" % err)

        u.GetMessageW.restype = ctypes.c_int
        msg = wintypes.MSG()
        while not self._stop.is_set():
            r = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                self.fired.put(int(msg.wParam))

        for hid in self.registered:
            try:
                u.UnregisterHotKey(None, hid)
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        try:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass


# ───────────────────────── 悬浮面板 ─────────────────────────

class OverlayPanel(tk.Toplevel):
    """紧凑的置顶面板。对外表现得像一个 Lane。"""

    def __init__(self, app, side="toPeer"):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.side = side                      # "toPeer" / "fromPeer"
        self._drag = (0, 0)
        self._alpha_i = 0
        self._rec_elapsed = 0.0

        self.title("假装外国人 · 悬浮")
        self.overrideredirect(True)           # 去掉标题栏，才像浮层
        self.attributes("-topmost", True)
        self.configure(bg=C_LINE)

        cfg = self.t.config
        self._alpha_i = 0
        for i, a in enumerate(ALPHAS):
            if abs(a - float(cfg.get("overlayAlpha", 1.0))) < 0.01:
                self._alpha_i = i
        self.attributes("-alpha", ALPHAS[self._alpha_i])

        self._build()
        self._restore_pos()
        self.refresh_memory()
        self.set_pair("")

    # ── 外观 ──

    def _build(self):
        outer = tk.Frame(self, bg=C_LINE)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        body = tk.Frame(outer, bg=C_BG)
        body.pack(fill="both", expand=True)

        # 标题栏（拖这里移动）
        bar = tk.Frame(body, bg=C_MINE)
        bar.pack(fill="x")

        # 先 pack 右边的：它们拿固定宽度，剩下的才给标题。
        # 反过来（标题先 pack）标题会先占掉自然宽度，右边几个被挤到重叠。
        for txt, cmd, tip in [("×", self.close, "关掉悬浮窗"),
                              ("◐", self.cycle_alpha, "透明度"),
                              ("⤢", self.open_main, "打开主窗口")]:
            b = tk.Label(bar, text=txt, bg=C_MINE, fg="#dfe7fb", font=FONT_S,
                         padx=6, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, c=cmd: c())
        # 会话下拉。注意不能给它绑拖动，否则点一下变成拖窗口、菜单打不开。
        self.btn_sess = tk.Menubutton(bar, text="会话", bg=C_MINE, fg="#eaf0ff",
                                      activebackground="#1d4ed8", activeforeground="white",
                                      font=FONT_S, relief="flat", padx=6, pady=0,
                                      cursor="hand2",
                                      indicatoron=False,   # 自带的小方块跟主题不搭，用文字里的 ▾
                                      highlightthickness=0, borderwidth=0)
        self.btn_sess.pack(side="right", padx=(4, 2))
        self.menu_sess = tk.Menu(self.btn_sess, tearoff=0, font=FONT_S)
        self.btn_sess.configure(menu=self.menu_sess)

        # 标题最后 pack，吃掉剩下的宽度（会话名太长也只是被挤窄，不会顶掉按钮）
        self.lbl_title = tk.Label(bar, text="假装外国人", bg=C_MINE, fg="#ffffff",
                                  font=FONT_B, anchor="w", padx=8, pady=3)
        self.lbl_title.pack(side="left", fill="x", expand=True)

        # 只有这几个地方能拖动窗口
        for w in (bar, self.lbl_title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # 方向切换
        sw = tk.Frame(body, bg=C_BG)
        sw.pack(fill="x", padx=6, pady=(6, 0))
        self.btn_a = tk.Button(sw, text="我 → 对方", font=FONT_S, relief="flat",
                               command=lambda: self.set_side("toPeer"))
        self.btn_a.pack(side="left")
        self.btn_b = tk.Button(sw, text="对方 → 我", font=FONT_S, relief="flat",
                               command=lambda: self.set_side("fromPeer"))
        self.btn_b.pack(side="left", padx=4)
        self.btn_clip = tk.Button(sw, text="剪贴板", font=FONT_S, relief="flat",
                                  command=self.translate_clipboard)
        self.btn_clip.pack(side="right")

        # 输入
        self.txt_in = tk.Text(body, height=4, wrap="word", font=FONT,
                              relief="solid", borderwidth=1, undo=True,
                              highlightthickness=0)
        self.txt_in.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        # 按钮行
        rb = tk.Frame(body, bg=C_BG)
        rb.pack(fill="x", padx=6, pady=4)
        self.btn_go = tk.Button(rb, text="翻译", font=FONT, bg=C_MINE, fg="white",
                                activebackground="#1d4ed8", activeforeground="white",
                                relief="flat", padx=12, command=self.do_translate)
        self.btn_go.pack(side="left")
        self.btn_mic = tk.Button(rb, text="🎤 说话", font=FONT_S, relief="flat",
                                 command=self.toggle_voice)
        self.btn_mic.pack(side="left", padx=4)
        self.lvl = tk.Canvas(rb, width=SPEAKER_W, height=SPEAKER_H,
                             highlightthickness=0, bd=0, bg=C_BG)
        draw_level(self.lvl, 0.0, C_MINE)
        self.btn_copy = tk.Button(rb, text="复制", font=FONT_S, relief="flat",
                                  command=self.copy_out)
        self.btn_copy.pack(side="left", padx=4)
        self.lbl_hint = tk.Label(rb, text="", bg=C_BG, fg=C_MUTED, font=FONT_S)
        self.lbl_hint.pack(side="right")

        # 译文
        self.txt_out = tk.Text(body, height=4, wrap="word", font=FONT,
                               relief="solid", borderwidth=1, bg=C_OUT_BG,
                               highlightthickness=0)
        self.txt_out.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        readonly_text(self.txt_out)

        self.txt_in.bind("<Control-Return>", lambda e: (self.do_translate(), "break")[1])
        self.txt_in.bind("<Escape>", lambda e: self.withdraw())

        self.update_side_buttons()
        self.refresh_session_label()

    def _restore_pos(self):
        cfg = self.t.config
        pos = cfg.get("overlayPos")
        w, h = 380, 330
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            sw = self.winfo_screenwidth()
            x, y = sw - w - 24, 120
        # 别跑到屏幕外面去
        x = max(0, min(x, self.winfo_screenwidth() - 80))
        y = max(0, min(y, self.winfo_screenheight() - 60))
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ── 拖动 / 吸边 ──

    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        self.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def _drag_end(self, _e=None):
        x, y = self.winfo_x(), self.winfo_y()
        sw = self.winfo_screenwidth()
        margin = 24
        if x <= margin:
            x = 0
        elif x + self.winfo_width() >= sw - margin:
            x = sw - self.winfo_width()
        self.geometry("+%d+%d" % (x, y))
        self.t.config["overlayPos"] = [x, y]
        self.t.save_config()

    # ── 标题栏动作 ──

    def open_main(self):
        a = self.app
        try:
            a.deiconify()
            a.lift()
            a.focus_force()
        except Exception:
            pass
        self.refresh_session_label()

    def cycle_alpha(self):
        self._alpha_i = (self._alpha_i + 1) % len(ALPHAS)
        v = ALPHAS[self._alpha_i]
        self.attributes("-alpha", v)
        self.t.config["overlayAlpha"] = v
        self.t.save_config()
        self.lbl_hint.configure(text="透明度 %d%%" % round(v * 100))

    def close(self):
        self.withdraw()

    def refresh_session_label(self):
        """把当前会话名和会话列表灌进下拉菜单。"""
        nm = self.t.active
        if len(nm) > 12:
            nm = nm[:11] + "…"
        self.btn_sess.configure(text="%s ▾" % nm)
        m = self.menu_sess
        m.delete(0, "end")

        for name in self.t.session_names():
            mark = "●  " if name == self.t.active else "    "
            m.add_command(label=mark + name,
                          command=lambda n=name: self.switch_session(n))
        m.add_separator()
        m.add_command(label="新建会话…", command=self.new_session)
        m.add_command(label="重命名当前…", command=self.rename_session)
        m.add_command(label="删除当前…", command=self.delete_session)
        m.add_separator()
        m.add_command(label="打开主窗口", command=self.open_main)

    def _apply_session_change(self, clear_output=True):
        """会话变了：主窗口那边也要跟着刷新，不然两边对不上。"""
        try:
            self.app.load_session_into_ui()
        except Exception:
            pass
        if clear_output:
            self.set_output("")
        self.refresh_memory()

    def switch_session(self, name):
        if name == self.t.active:
            return
        self.t.switch_session(name)
        self._apply_session_change()
        self.flash("已切到 %s" % name)

    def new_session(self):
        name = simpledialog.askstring("新建会话", "会话名（一般写 Claude / GPT 那边的任务名）：",
                                      parent=self)
        if not name:
            return
        name = name.strip()
        if not self.t.add_session(name):
            messagebox.showwarning("重名", "已经有同名会话了。", parent=self)
            return
        self._apply_session_change()
        self.flash("已新建 %s" % name)

    def rename_session(self):
        old = self.t.active
        new = simpledialog.askstring("重命名", "新名字：", initialvalue=old, parent=self)
        if not new:
            return
        self.t.rename_session(old, new.strip())
        self._apply_session_change(clear_output=False)

    def delete_session(self):
        if len(self.t.sessions) <= 1:
            messagebox.showinfo("不能删", "至少留一个会话。", parent=self)
            return
        if not messagebox.askyesno(
                "删除会话", "删掉「%s」以及它的两条记忆线？" % self.t.active, parent=self):
            return
        self.t.delete_session(self.t.active)
        self._apply_session_change()
        self.flash("已删除")

    # ── 方向 ──

    def set_side(self, side):
        self.side = side
        self.update_side_buttons()
        self.refresh_memory()

    def update_side_buttons(self):
        for btn, sd, col in ((self.btn_a, "toPeer", C_MINE),
                             (self.btn_b, "fromPeer", C_PEER)):
            on = (self.side == sd)
            btn.configure(bg=col if on else "#e8ecf1",
                          fg="white" if on else "#333333",
                          activebackground=col, activeforeground="white")

    def toggle_side(self):
        self.set_side("fromPeer" if self.side == "toPeer" else "toPeer")

    # ── Lane 接口（主窗口的翻译/录音流程直接用这几个）──

    def get_input(self):
        return self.txt_in.get("1.0", "end").strip()

    def set_input(self, text):
        self.txt_in.delete("1.0", "end")
        if text:
            self.txt_in.insert("1.0", text)

    def set_output(self, text):
        self.txt_out.delete("1.0", "end")
        self.txt_out.insert("1.0", text)

    def get_output(self):
        return self.txt_out.get("1.0", "end").strip()

    def set_pair(self, text):
        pass                                  # 悬浮窗位置紧，不显示语言对

    def set_busy(self, busy):
        self.btn_go.configure(state="disabled" if busy else "normal",
                              bg="#a9bce8" if busy else C_MINE)

    def set_recording(self, on, elapsed=0.0):
        if on:
            self.btn_mic.configure(text="■ 停止")
            self.lvl.pack(side="left", padx=(0, 2), before=self.btn_copy)
            self.lbl_hint.configure(text="0.0s   Esc 取消")
        else:
            self.btn_mic.configure(text="🎤 说话")
            draw_level(self.lvl, 0.0, self.accent())
            try:
                self.lvl.pack_forget()
            except Exception:
                pass
            self.lbl_hint.configure(text="")

    def set_level(self, v, elapsed=0.0, raw=None):
        draw_level(self.lvl, v, self.accent())
        tail = "" if raw is None else ("  电平 %d%%" % round(raw * 100))
        self.lbl_hint.configure(text="%.1fs%s" % (elapsed, tail))

    def refresh_memory(self):
        """悬浮窗不摆记忆列表，只把条数写到标题上。"""
        n = len(self.t.memory(self.side))
        base = "假装外国人"
        if n:
            base += "  ·  %d 条" % n
        self.lbl_title.configure(text=base)
        self.refresh_session_label()

    def accent(self):
        return C_PEER if self.side == "fromPeer" else C_MINE

    # ── 动作 ──

    def do_translate(self):
        if self.app.recording_target is not None:
            self.app.status("先把录音停掉")
            return
        self.app.translate_lane(self)

    def toggle_voice(self):
        self.app.toggle_voice(self)

    def copy_out(self):
        txt = self.get_output()
        if not txt:
            self.app.status("还没有译文")
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.lbl_hint.configure(text="已复制")

    def translate_clipboard(self):
        try:
            txt = self.clipboard_get()
        except Exception:
            self.app.status("剪贴板是空的")
            return
        txt = (txt or "").strip()
        if not txt:
            self.app.status("剪贴板是空的")
            return
        self.set_input(txt)
        self.do_translate()

    def flash(self, msg):
        self.lbl_hint.configure(text=msg)
        self.after(2500, lambda: self.lbl_hint.configure(text=""))


# ───────────────────────── 接线 ─────────────────────────

def install_hotkeys(app, toggle_hotkey=True, clip_hotkey=True):
    """给主窗口装上全局快捷键，键位从 config 读，方便改。

    config["hotkeyToggle"] / ["hotkeyClipboard"] 的格式是 [修饰键, 虚拟键码]。
    返回 HotkeyThread（注册失败的记在 .failed 里，带错误码和原因）。
    """
    cfg = app.t.config
    t_mods, t_vk = cfg.get("hotkeyToggle") or DEFAULT_TOGGLE
    c_mods, c_vk = cfg.get("hotkeyClipboard") or DEFAULT_CLIP

    keys = {}
    if toggle_hotkey:
        keys[1] = (t_mods, t_vk, "%s 悬浮窗" % key_name(t_mods, t_vk))
    if clip_hotkey:
        keys[2] = (c_mods, c_vk, "%s 翻剪贴板" % key_name(c_mods, c_vk))

    th = HotkeyThread(keys)
    th.start()

    def poll():
        try:
            while True:
                hid = th.fired.get_nowait()
                if hid == 1:
                    app.toggle_overlay()
                elif hid == 2:
                    app.overlay_clipboard()
        except queue.Empty:
            pass
        app.after(120, poll)

    app.after(200, poll)
    return th


def hotkey_pair(app):
    """当前生效的两个键 —— (toggle, clip)，都从 config 读、都有默认值。

    界面上任何要提到"按哪个键"的地方都必须从这里取，**不许写死键名**。
    踩过两次：键位从 Ctrl+Alt 换成 Win+Alt 之后，状态栏和悬浮窗提示里的旧字符串
    都没跟着改，界面上一直在报已经废弃的键，和 README 对不上。
    """
    cfg = app.t.config
    return ((cfg.get("hotkeyToggle") or DEFAULT_TOGGLE),
            (cfg.get("hotkeyClipboard") or DEFAULT_CLIP))


def toggle_key_name(app):
    """当前"显示/隐藏悬浮窗"的键名。"""
    return key_name(*hotkey_pair(app)[0])


def hotkey_help(app):
    """给设置界面显示用：当前键位 + 能不能用。"""
    (t_mods, t_vk), (c_mods, c_vk) = hotkey_pair(app)
    return ("%s  显示/隐藏悬浮窗\n%s  翻译剪贴板"
            % (key_name(t_mods, t_vk), key_name(c_mods, c_vk)))


def hotkey_line(app):
    """状态栏用的一行键位说明。"""
    (t_mods, t_vk), (c_mods, c_vk) = hotkey_pair(app)
    return ("%s 悬浮窗 · %s 翻剪贴板"
            % (key_name(t_mods, t_vk), key_name(c_mods, c_vk)))


# ───────────────────────── 改键位 ─────────────────────────

PROBE_ID = 9001          # 试注册用的临时 id，别和正式键（1 / 2）撞


def probe_hotkey(mods, vk, timeout=1.5):
    """试着注册一次然后立刻注销。返回 (能不能用, 原因)。

    设置界面在用户选完键位后调它 —— 冲突要当场报出来，不能静默通过。
    """
    if not mods:
        return False, "至少要一个修饰键（Ctrl / Alt / Shift / Win）"
    th = HotkeyThread({PROBE_ID: (mods, vk, key_name(mods, vk))})
    th.start()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if th.registered or th.failed:
            break
        time.sleep(0.05)
    th.stop()
    if th.registered:
        return True, ""
    if th.failed:
        return False, th.failed[PROBE_ID][2]
    return False, "注册结果未知（超时）"


def apply_hotkeys(app):
    """停掉旧的、按当前 config 重新装一遍。返回 (成不成, 说明)。

    设置里改完键位当场调它 —— 不用重启程序。
    """
    old = getattr(app, "hotkeys", None)
    if old is not None:
        try:
            old.stop()
        except Exception:
            pass
        time.sleep(0.25)     # 等旧线程把键注销掉，否则同一个键会注册失败
    th = install_hotkeys(app)
    app.hotkeys = th
    if th.failed:
        return False, "；".join("%s → %s" % (v[0], v[2]) for v in th.failed.values())
    return True, hotkey_line(app)
