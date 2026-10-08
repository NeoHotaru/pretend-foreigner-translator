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
from island_window import (IslandWindow, ISLAND_BG, ISLAND_FIELD, ISLAND_TEXT,
                           ISLAND_MUTED, ISLAND_LINE, PILL_SIZE)

from ui_kit import (C_BG, C_LINE, C_MINE, C_MUTED, C_OUT_BG, C_PEER,
                    C_TEXT, C_SURFACE, FONT_UI, FONT_SMALL, FONT_HEAD,
                    SPEAKER_H, SPEAKER_W, draw_level, norm_level, readonly_text, text_surface, brand_icon)

FONT = FONT_UI
FONT_S = FONT_SMALL
FONT_B = FONT_HEAD

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

class OverlayPanel(IslandWindow):
    """紧凑的置顶面板。对外表现得像一个 Lane。"""

    def __init__(self, app, side="toPeer"):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.side = side                      # "toPeer" / "fromPeer"
        self._drag = (0, 0)
        self._alpha_i = 0
        self._rec_elapsed = 0.0
        self._busy = False
        self._recording = False
        self._flash_id = None

        self.title("假装外国人 · 悬浮")
        self.overrideredirect(True)           # 去掉标题栏，才像浮层
        self.attributes("-topmost", True)
        self.configure(bg=ISLAND_BG)

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

    def _quiet_button(self, master, text, command, **kwargs):
        return tk.Button(master, text=text, command=command, font=FONT_S,
                         bg=ISLAND_BG, fg=ISLAND_MUTED, activebackground="#2c3440",
                         activeforeground=ISLAND_TEXT, relief="flat", bd=0,
                         padx=8, pady=7, cursor="hand2", **kwargs)

    def _build(self):
        self._pill = tk.Frame(self, bg=ISLAND_BG, takefocus=True, cursor="hand2")
        self._pill_icon = brand_icon(self, 24)
        logo = tk.Label(self._pill, image=self._pill_icon, bg=ISLAND_BG, cursor="hand2")
        logo.pack(side="left", padx=(17, 9))
        self.pill_title = tk.Label(self._pill, text="假装外国人", font=FONT,
                                   bg=ISLAND_BG, fg=ISLAND_TEXT, cursor="hand2")
        self.pill_title.pack(side="left")
        self.pill_status = tk.Label(self._pill, text="⇄", font=("Segoe UI", 11),
                                    bg=ISLAND_BG, fg="#73cbbb", cursor="hand2", width=6)
        self.pill_status.pack(side="right", padx=(0, 13))
        for widget in (self._pill, logo, self.pill_title, self.pill_status):
            self.bind_drag(widget, activates=True)
            widget.bind("<Button-3>", self._context_menu)
        self._pill.bind("<Return>", lambda e: self.expand(animate=False))
        self._pill.bind("<space>", lambda e: self.expand(animate=False))

        self._panel = tk.Frame(self, bg=ISLAND_BG)
        body = tk.Frame(self._panel, bg=ISLAND_BG)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        body.rowconfigure(7, weight=1)
        bar = tk.Frame(body, bg=ISLAND_BG)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.btn_collapse = self._quiet_button(bar, "收起", self.close)
        self.btn_collapse.pack(side="right")
        self._quiet_button(bar, "主界面", self.open_main).pack(side="right")
        self._brand_icon = brand_icon(self, 24)
        self.lbl_title = tk.Label(bar, text="假装外国人", bg=ISLAND_BG, fg=ISLAND_TEXT,
                                  image=self._brand_icon, compound="left", padx=5,
                                  font=FONT_B, anchor="w", cursor="fleur")
        self.lbl_title.pack(side="left", fill="x", expand=True)
        for widget in (bar, self.lbl_title):
            self.bind_drag(widget)

        session = tk.Frame(body, bg=ISLAND_BG)
        session.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.btn_sess = tk.Menubutton(session, text="会话", bg=ISLAND_BG, fg=ISLAND_MUTED,
                                      activebackground="#2c3440", activeforeground=ISLAND_TEXT,
                                      font=FONT_S, relief="flat", padx=5, pady=5,
                                      cursor="hand2", indicatoron=False, bd=0,
                                      highlightthickness=0, anchor="w", takefocus=True)
        self.btn_sess.pack(side="left", fill="x", expand=True)
        self.menu_sess = tk.Menu(self.btn_sess, tearoff=0, font=FONT_S)
        self.btn_sess.configure(menu=self.menu_sess)
        tk.Label(session, text="两边各记各的话", font=FONT_S,
                 bg=ISLAND_BG, fg=ISLAND_MUTED).pack(side="right")

        sw = tk.Frame(body, bg=ISLAND_FIELD, padx=3, pady=3)
        sw.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.btn_a = tk.Button(sw, text="我 → 对方", font=FONT_S, relief="flat", bd=0,
                               padx=12, pady=8, cursor="hand2", command=lambda: self.set_side("toPeer"))
        self.btn_a.pack(side="left", fill="x", expand=True)
        self.btn_b = tk.Button(sw, text="对方 → 我", font=FONT_S, relief="flat", bd=0,
                               padx=12, pady=8, cursor="hand2", command=lambda: self.set_side("fromPeer"))
        self.btn_b.pack(side="left", fill="x", expand=True, padx=(3, 0))

        input_head = tk.Frame(body, bg=ISLAND_BG)
        input_head.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.lbl_input = tk.Label(input_head, text="你的原话", font=FONT_S,
                                  bg=ISLAND_BG, fg=ISLAND_MUTED)
        self.lbl_input.pack(side="left")
        self.btn_clip = self._quiet_button(input_head, "翻译剪贴板", self.translate_clipboard)
        self.btn_clip.pack(side="right")

        self.lbl_hint = tk.Label(body, text="Ctrl+Enter 翻译", bg=ISLAND_BG, fg=ISLAND_MUTED,
                                 font=FONT_S, anchor="w", wraplength=374, justify="left")
        self.lbl_hint.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        output_surface, self.txt_out = self._text_area(body, undo=False)
        output_surface.grid(row=7, column=0, sticky="nsew")
        readonly_text(self.txt_out)
        out_head = tk.Frame(body, bg=ISLAND_BG)
        out_head.grid(row=6, column=0, sticky="ew", pady=(6, 6))
        self.lbl_output = tk.Label(out_head, text="发给对方", font=FONT_S,
                                   bg=ISLAND_BG, fg=ISLAND_MUTED)
        self.lbl_output.pack(side="left")
        self.btn_copy = self._quiet_button(out_head, "复制译文", self.copy_out)
        self.btn_copy.pack(side="right")

        rb = tk.Frame(body, bg=ISLAND_BG)
        rb.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.btn_go = ttk.Button(rb, text="翻译", style="Go.TButton", width=6, command=self.do_translate)
        self.btn_go.pack(side="left")
        self.btn_mic = self._quiet_button(rb, "语音输入", self.toggle_voice)
        self.btn_mic.pack(side="left", padx=(8, 0))
        self.lvl = tk.Canvas(rb, width=SPEAKER_W, height=SPEAKER_H,
                             highlightthickness=0, bd=0, bg=ISLAND_BG)
        draw_level(self.lvl, 0.0, C_MINE)
        input_surface, self.txt_in = self._text_area(body, undo=True)
        input_surface.grid(row=4, column=0, sticky="nsew")

        self.txt_in.bind("<Control-Return>", lambda e: (self.do_translate(), "break")[1])
        self.bind("<Escape>", self._escape)
        self.update_side_buttons()
        self.refresh_session_label()

    def _text_area(self, master, undo):
        frame, widget = text_surface(master, height=4, font=FONT, undo=undo,
                                     bg=ISLAND_FIELD, fg=ISLAND_TEXT,
                                     insertbackground=ISLAND_TEXT, selectforeground="white")
        frame.configure(highlightbackground=ISLAND_LINE)
        widget.bind("<FocusOut>", lambda e: frame.configure(highlightbackground=ISLAND_LINE), add="+")
        style = ttk.Style(self)
        style.configure("Island.Vertical.TScrollbar", background="#3a4555", troughcolor=ISLAND_FIELD,
                        arrowcolor=ISLAND_MUTED, borderwidth=0)
        for child in frame.winfo_children():
            if isinstance(child, ttk.Scrollbar):
                child.configure(style="Island.Vertical.TScrollbar")
        return frame, widget

    def _restore_pos(self):
        cfg = self.t.config
        pos = cfg.get("overlayIslandPos")
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            old = cfg.get("overlayPos")
            pos = [old[0] + (420 - PILL_SIZE[0]) / 2, old[1]] if isinstance(old, (list, tuple)) and len(old) == 2 else [self.winfo_screenwidth() - PILL_SIZE[0] - 24, 120]
        try:
            self.initialize_island([float(pos[0]), float(pos[1])])
        except (TypeError, ValueError):
            self.initialize_island([self.winfo_screenwidth() - PILL_SIZE[0] - 24, 120])

    def _escape(self, _event=None):
        if self.app.recording_target is not None:
            self.app.cancel_recording()
        else:
            self.collapse(animate=False)
        return "break"

    def _context_menu(self, event):
        previous = getattr(self, "_island_menu", None)
        if previous is not None:
            previous.destroy()
        menu = self._island_menu = tk.Menu(self, tearoff=0, font=FONT_S)
        menu.add_command(label="收起翻译面板" if self.expanded else "展开翻译面板",
                         command=self.toggle_expanded)
        menu.add_command(label="翻译剪贴板", command=self.translate_clipboard)
        menu.add_separator()
        menu.add_command(label="返回主界面", command=self.open_main)
        menu.add_command(label="调整透明度", command=self.cycle_alpha)
        menu.add_command(label="隐藏悬浮岛", command=self.hide)
        def dismissed(_event=None):
            self._context_open = False
            self._queue_focus_check()
        menu.bind("<Unmap>", dismissed)
        self._context_open = True
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _update_pill(self, message=None):
        if self._recording:
            message = "录音"
        elif self._busy:
            message = "翻译中"
        self.pill_status.configure(text=message or "⇄")

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
        self.collapse(animate=False)

    def cycle_alpha(self):
        self._alpha_i = (self._alpha_i + 1) % len(ALPHAS)
        v = ALPHAS[self._alpha_i]
        self.attributes("-alpha", v)
        self.t.config["overlayAlpha"] = v
        self.t.save_config()
        self.lbl_hint.configure(text="透明度 %d%%" % round(v * 100))

    def close(self):
        self.collapse()

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
        if self.app.busy or self.app.recording_target is self:
            self.flash("完成当前翻译或录音后再切换方向")
            return
        self.side = side
        self.update_side_buttons()
        self.refresh_memory()

    def update_side_buttons(self):
        for btn, sd, col in ((self.btn_a, "toPeer", C_MINE),
                             (self.btn_b, "fromPeer", C_PEER)):
            on = (self.side == sd)
            btn.configure(bg=col if on else ISLAND_FIELD,
                          fg="white" if on else ISLAND_MUTED,
                          activebackground=col, activeforeground="white")
        self.btn_go.configure(style="PeerGo.TButton" if self.side == "fromPeer" else "Go.TButton")
        self.lbl_input.configure(text="对方的原文" if self.side == "fromPeer" else "你的原话")
        self.lbl_output.configure(text="对方的意思" if self.side == "fromPeer" else "发给对方")

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
        self.lbl_hint.configure(text=(text + "；已自动复制") if text else "Ctrl+Enter 翻译")
        if text:
            self._update_pill("已复制")

    def set_busy(self, busy):
        self._busy = busy
        self.btn_go.configure(state="disabled" if busy else "normal",
                              text="翻译中…" if busy else "翻译")
        if busy:
            self.lbl_hint.configure(text="正在翻译…")
        self._update_pill()

    def set_recording(self, on, elapsed=0.0):
        self._recording = on
        if on:
            self.btn_mic.configure(text="■ 停止")
            self.lvl.pack(side="left", padx=(6, 0), after=self.btn_mic)
            self.lbl_hint.configure(text="0.0s   Esc 取消")
        else:
            self.btn_mic.configure(text="语音输入")
            draw_level(self.lvl, 0.0, self.accent())
            try:
                self.lvl.pack_forget()
            except Exception:
                pass
            self.lbl_hint.configure(text="Ctrl+Enter 翻译")
        self._update_pill()

    def set_level(self, v, elapsed=0.0, raw=None):
        draw_level(self.lvl, v, self.accent())
        tail = "" if raw is None else ("  电平 %d%%" % round(raw * 100))
        self.lbl_hint.configure(text="%.1fs%s" % (elapsed, tail))

    def refresh_memory(self):
        """会话菜单同步当前会话，输入提示同步方向和记忆数量。"""
        self.lbl_title.configure(text="假装外国人")
        n = len(self.t.memory(self.side))
        self.lbl_input.configure(text="%s · 记忆 %d 条" % (
            "对方的原文" if self.side == "fromPeer" else "你的原话", n))
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
        self.flash("已复制")

    def translate_clipboard(self):
        self.expand(animate=False, focus=False)
        try:
            txt = self.clipboard_get()
        except Exception:
            self.flash("剪贴板是空的")
            return
        txt = (txt or "").strip()
        if not txt:
            self.flash("剪贴板是空的")
            return
        self.set_input(txt)
        self.do_translate()

    def flash(self, msg):
        self._cancel("_flash_id")
        self.lbl_hint.configure(text=msg)
        self._update_pill("失败" if "失败" in msg else "已复制" if "复制" in msg else "⇄")
        def clear():
            self._flash_id = None
            self.lbl_hint.configure(text="Ctrl+Enter 翻译")
            self._update_pill()
        self._flash_id = self.after(4000, clear)


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
