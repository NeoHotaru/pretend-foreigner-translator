# -*- coding: utf-8 -*-
"""
translate_app.py  —  假装外国人翻译器 · tkinter 前端

这个文件**只负责显示**。所有逻辑（提示词、API、记忆、会话、语言判定）
都在 translator_core.py 里。

要换前端（QT / Web / 命令行）时，把这个文件整个丢掉，
按 CORE_API.md 调 Translator 就行，一行后端代码都不用动。

启动：pythonw translate_app.py
"""

import ctypes
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from voice_input import AsrClient, Recorder, list_input_devices, default_input_device
from translator_core import log

from translator_core import (
    APP_NAME,
    BUDGET_MAX,
    BUDGET_MIN,
    BUDGET_STEP,
    CODE_OF_LABEL,
    LANGS,
    MEM_MAX,
    MEM_MIN,
    MODE_CODES,
    Translator,
    pick_context,
    clamp_budget,
    clamp_depth,
    lang_name,
)

WINDOW_TITLE = APP_NAME + "  ·  Pretend Foreigner Translator"
DEFAULT_GEOMETRY = "1240x860"

# ───────────────────────── 外观 ─────────────────────────

# 颜色统一从 ui_kit 取，别各定义一份（改主题只改一个地方）
from ui_kit import (C_BAD, C_BG, C_LINE, C_MINE, C_MUTED,  # noqa: E402
                    C_OK, C_OUT_BG, C_PEER, C_TEXT, C_SURFACE, C_SIDEBAR,
                    FONT_UI, FONT_SMALL, FONT_HEAD, FONT_TEXT, FONT_TITLE,
                    text_surface, readonly_text, apply_app_icon)


def setup_style(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass

    st.configure(".", font=FONT_UI, background=C_BG)
    st.configure("TFrame", background=C_BG)
    st.configure("TLabel", background=C_BG, foreground=C_TEXT)
    st.configure("Hint.TLabel", background=C_BG, foreground=C_MUTED, font=FONT_SMALL)
    st.configure("Head.TLabel", background=C_BG, foreground=C_TEXT, font=FONT_HEAD)
    st.configure("Title.TLabel", background=C_BG, foreground=C_TEXT, font=FONT_TITLE)
    st.configure("Card.TFrame", background=C_SURFACE)
    st.configure("Card.TLabel", background=C_SURFACE, foreground=C_TEXT)
    st.configure("CardHint.TLabel", background=C_SURFACE, foreground=C_MUTED, font=FONT_SMALL)
    st.configure("CardHead.TLabel", background=C_SURFACE, foreground=C_TEXT, font=FONT_HEAD)
    st.configure("Side.TFrame", background=C_SIDEBAR)
    st.configure("Side.TLabel", background=C_SIDEBAR, foreground=C_TEXT)
    st.configure("SideHint.TLabel", background=C_SIDEBAR, foreground=C_MUTED, font=FONT_SMALL)

    st.configure("TButton", padding=(12, 7), font=FONT_UI, background=C_SURFACE,
                 foreground=C_TEXT, borderwidth=1, relief="flat")
    st.map("TButton", background=[("pressed", "#dce5ef"), ("active", "#e9eff6")])
    st.configure("Quiet.TButton", padding=(8, 6), font=FONT_SMALL, borderwidth=0)
    st.configure("Side.TButton", background=C_SIDEBAR, font=FONT_SMALL, padding=(8, 7))

    st.configure("Go.TButton", padding=(18, 8), font=FONT_UI,
                 foreground="#ffffff", background=C_MINE)
    st.map("Go.TButton",
           background=[("disabled", "#a3b8d3"), ("pressed", "#173e77"), ("active", "#1c4b8f")],
           foreground=[("disabled", "#eef2ff")])
    st.configure("PeerGo.TButton", padding=(18, 8), font=FONT_UI,
                 foreground="white", background=C_PEER)
    st.map("PeerGo.TButton", background=[("disabled", "#97bcb6"),
           ("pressed", "#075b52"), ("active", "#06685e")],
           foreground=[("disabled", "#eef7f5")])

    st.configure("TEntry", fieldbackground=C_SURFACE, padding=7, bordercolor=C_LINE)
    st.configure("TCombobox", padding=6, arrowsize=14, bordercolor=C_LINE)
    st.map("TCombobox", fieldbackground=[("readonly", C_SURFACE)],
           selectbackground=[("readonly", C_SURFACE)],
           selectforeground=[("readonly", C_TEXT)])
    st.configure("TSpinbox", padding=6, bordercolor=C_LINE)
    st.configure("TPanedwindow", background=C_BG)
    st.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                 rowheight=30, font=FONT_SMALL, borderwidth=0)
    st.configure("Treeview.Heading", font=FONT_SMALL, padding=(8, 6), background=C_BG)
    st.configure("Status.TLabel", background=C_BG, foreground="#4b5563", font=FONT_SMALL)
    return st


# 喇叭绘制挪到 ui_kit.py（悬浮窗也要用，避免循环导入）
from ui_kit import (C_BG as _UBG, SPEAKER_H, SPEAKER_W,  # noqa: F401
                    clip_poly_below, draw_level, norm_level)

def single_instance_guard():
    """已经有窗口就把它拉到前台，然后让本次启动安静退出。

    不让两个窗口同时开：它们共用同一份会话文件，退出时后写的会覆盖先写的。
    ctypes 默认不捕获 last error，GetLastError() 取到的值不可靠，所以用 FindWindowW。
    """
    try:
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        hwnd = u.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return True
        u.ShowWindow(hwnd, 9)              # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return False
    except Exception:
        return True


class PlaceholderText(tk.Text):
    """带灰色提示文字的输入框，聚焦即消失。"""

    def __init__(self, master, placeholder="", **kw):
        super().__init__(master, **kw)
        self.placeholder = placeholder
        self._has_ph = False
        self._fg = self.cget("fg")
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.put_placeholder()

    def put_placeholder(self):
        if self.placeholder and not super().get("1.0", "end").strip():
            self._has_ph = True
            self.insert("1.0", self.placeholder)
            self.configure(fg=C_MUTED)

    def _focus_in(self, _e=None):
        if self._has_ph:
            self.delete("1.0", "end")
            self.configure(fg=self._fg)
            self._has_ph = False

    def _focus_out(self, _e=None):
        if not super().get("1.0", "end").strip():
            self.put_placeholder()

    def get_value(self):
        if self._has_ph:
            return ""
        return super().get("1.0", "end").strip()

    def set_value(self, text):
        if self._has_ph:
            self.delete("1.0", "end")
            self.configure(fg=self._fg)
            self._has_ph = False
        self.delete("1.0", "end")
        if text:
            self.insert("1.0", text)

    def clear_value(self):
        if self._has_ph:
            self.delete("1.0", "end")
            self.configure(fg=self._fg)
            self._has_ph = False
        self.delete("1.0", "end")
        self.put_placeholder()


# ───────────────────────── 一栏 ─────────────────────────

class Lane(ttk.Frame):
    """一栏：输入 -> 翻译 -> 译文，外加本栏自己的记忆。"""

    def __init__(self, master, side, accent, on_translate, on_copy, on_voice, app):
        super().__init__(master, style="Card.TFrame", padding=20)
        self.app = app
        self.side = side                      # "toPeer" / "fromPeer"
        self.accent = accent

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        strip = ttk.Frame(self, style="Card.TFrame")
        strip.grid(row=0, column=0, sticky="ew")
        strip.columnconfigure(1, weight=1)
        self.lbl_title = tk.Label(strip, text="", bg=C_SURFACE, fg=accent,
                                  font=FONT_HEAD, anchor="w")
        self.lbl_title.grid(row=0, column=0, sticky="w")
        self.lbl_pair = tk.Label(strip, text="", bg=C_SURFACE, fg=C_MUTED,
                                 font=FONT_SMALL, anchor="w")
        self.lbl_pair.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 18))

        pad = ttk.Frame(self, style="Card.TFrame")
        pad.grid(row=1, column=0, sticky="nsew")
        pad.columnconfigure(0, weight=1)
        pad.rowconfigure(1, weight=1)         # 输入
        pad.rowconfigure(5, weight=1)         # 译文

        ttk.Label(pad, text="你的原话" if side == "toPeer" else "对方的原文",
                  style="CardHint.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        surface, self.txt_in = text_surface(
            pad, PlaceholderText, placeholder="写下你想说的话，也可以用语音输入…"
            if side == "toPeer" else "粘贴对方的回复…", height=6, undo=True)
        surface.grid(row=1, column=0, sticky="nsew")

        bar = ttk.Frame(pad, style="Card.TFrame")
        bar.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.btn_go = ttk.Button(bar, text="翻译", style="Go.TButton"
                                 if side == "toPeer" else "PeerGo.TButton",
                                 command=on_translate, width=6)
        self.btn_go.pack(side="left")
        self.btn_mic = ttk.Button(bar, text="语音输入", command=on_voice, width=8)
        self.btn_mic.pack(side="left", padx=(8, 4))
        # 喇叭电平表：灰色底座，蓝色从下往上填，只在录音时出现
        self.lvl = tk.Canvas(bar, width=SPEAKER_W, height=SPEAKER_H,
                             highlightthickness=0, bd=0, bg=C_SURFACE)
        self._draw_level(0.0)
        self.btn_clear = ttk.Button(bar, text="清空", command=self.clear_all,
                                    style="Quiet.TButton", width=5)
        self.btn_clear.pack(side="right")
        self.lbl_hint = ttk.Label(pad, text="Ctrl+Enter 翻译", style="CardHint.TLabel")
        self.lbl_hint.grid(row=3, column=0, sticky="w", pady=(6, 14))

        out_head = ttk.Frame(pad, style="Card.TFrame")
        out_head.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(out_head, text="发给对方" if side == "toPeer" else "对方的意思",
                  style="CardHint.TLabel").pack(side="left")
        self.btn_copy = ttk.Button(out_head, text="复制译文", command=on_copy,
                                   style="Quiet.TButton", width=9)
        self.btn_copy.pack(side="right")
        surface, self.txt_out = text_surface(pad, height=6, bg=C_OUT_BG)
        surface.grid(row=5, column=0, sticky="nsew")
        readonly_text(self.txt_out)

        memory_head = ttk.Frame(pad, style="Card.TFrame")
        memory_head.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        self.btn_memory = ttk.Button(memory_head, text="查看记忆  ▾",
                                      style="Quiet.TButton", command=self.toggle_memory)
        self.btn_memory.pack(side="left")
        ttk.Label(memory_head, text="翻译完成后自动复制", style="CardHint.TLabel").pack(side="right")
        self.memory_open = False
        # 独立、非模态的历史窗口，查看记忆时仍能阅读和编辑译文。
        self.memory_window = tk.Toplevel(self)
        self.memory_window.withdraw()
        self.memory_window.title("本侧会话记忆")
        self.memory_window.configure(bg=C_SURFACE)
        self.memory_window.transient(app)
        self.memory_window.geometry("640x420")
        self.memory_window.minsize(480, 320)
        self.memory_window.protocol("WM_DELETE_WINDOW", self.toggle_memory)
        self.memory_window.bind("<Escape>", lambda e: self.toggle_memory())
        self.memory_panel = mem = ttk.Frame(self.memory_window, style="Card.TFrame", padding=18)
        mem.pack(fill="both", expand=True)
        mem.columnconfigure(0, weight=1)
        mem.rowconfigure(1, weight=1)

        head = ttk.Frame(mem, style="Card.TFrame")
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.lbl_mem = ttk.Label(head, text="本栏记忆", style="CardHint.TLabel", wraplength=420)
        self.lbl_mem.pack(side="left")

        cols = ("src", "out", "on")
        self.tree = ttk.Treeview(mem, columns=cols, show="headings",
                                 selectmode="extended", height=3)
        self.tree.heading("src", text="原文")
        self.tree.heading("out", text="译文")
        self.tree.heading("on", text="本次")
        self.tree.column("src", width=190, stretch=True, anchor="w")
        self.tree.column("out", width=190, stretch=True, anchor="w")
        self.tree.column("on", width=44, stretch=False, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(mem, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._recall)

        mbar = ttk.Frame(mem, style="Card.TFrame")
        mbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(mbar, text="删除选中", command=self.del_selected,
                   style="Quiet.TButton", width=8).pack(side="left")
        ttk.Button(mbar, text="清空本栏", command=self.clear_memory,
                   style="Quiet.TButton", width=8).pack(side="left", padx=4)
        ttk.Button(mbar, text="复制选中原文", command=self.copy_selected_src,
                   style="Quiet.TButton", width=11).pack(side="left")
        ttk.Label(mem, text="双击回填原文；可按住 Ctrl 多选", style="CardHint.TLabel").grid(
            row=3, column=0, sticky="w", pady=(6, 0))

        self.txt_in.bind("<Control-Return>", lambda e: (on_translate(), "break")[1])

    def toggle_memory(self):
        self.memory_open = not self.memory_open
        if self.memory_open:
            self.memory_window.deiconify()
            self.memory_window.lift()
        else:
            self.memory_window.withdraw()
        self.refresh_memory()

    # — 标题 —

    def set_title(self, text):
        self.lbl_title.configure(text=text)
        self.memory_window.title(text + " · 会话记忆")

    def set_pair(self, text):
        self.lbl_pair.configure(text=text)

    # — 基本 —

    def get_input(self):
        return self.txt_in.get_value()

    def set_input(self, text):
        self.txt_in.set_value(text)

    def set_output(self, text):
        self.txt_out.delete("1.0", "end")
        self.txt_out.insert("1.0", text)

    def get_output(self):
        return self.txt_out.get("1.0", "end").strip()

    def clear_all(self):
        self.txt_in.clear_value()
        self.txt_out.delete("1.0", "end")

    def set_busy(self, busy):
        self.btn_go.configure(state="disabled" if busy else "normal",
                              text="翻译中…" if busy else "翻译")

    def set_recording(self, on, elapsed=0.0):
        if on:
            self.btn_mic.configure(text="■ 停止")
            self._draw_level(0.0)
            self.lvl.pack(side="left", padx=(0, 2), after=self.btn_mic)
            self.lbl_hint.configure(text="0.0s   Esc 取消")
        else:
            self.btn_mic.configure(text="语音输入")
            self._draw_level(0.0)
            try:
                self.lvl.pack_forget()          # 录完收起来，别留个空条
            except Exception:
                pass
            self.lbl_hint.configure(text="Ctrl+Enter 翻译")

    def _draw_level(self, v):
        draw_level(self.lvl, v, self.accent)

    def set_level(self, v, elapsed=0.0, raw=None):
        self._draw_level(v)
        tail = "" if raw is None else ("  电平 %d%%" % round(raw * 100))
        self.lbl_hint.configure(text="%.1fs%s   Esc 取消" % (elapsed, tail))

    # — 记忆（数据在 core 里，这里只显示）—

    def refresh_memory(self):
        arr = self.app.t.memory(self.side)
        cfg = self.app.t.config
        depth = clamp_depth(cfg.get("memoryDepth", 8))
        budget = clamp_budget(cfg.get("contextCharBudget", 12000))

        # pick_context 取的是最近 depth 条里能塞进预算的那部分，
        # 而且一定是从末尾往前连续的，所以活跃区间就是一个后缀。
        active, chars = pick_context(arr, depth, budget)
        first = len(arr) - len(active)

        self.tree.delete(*self.tree.get_children())
        for i, h in enumerate(arr):
            self.tree.insert("", "end", values=(
                h.get("src", "").replace("\n", " "),
                h.get("out", "").replace("\n", " "),
                "✓" if i >= first else ""))
        self.lbl_mem.configure(
            text="本栏记忆  已积累 %d 条 · 本次带 %d 条 / %d 字"
                 % (len(arr), len(active), chars))
        self.btn_memory.configure(text="%s记忆 %d 条" % (
            "关闭" if self.memory_open else "查看", len(arr)))

    def _recall(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if vals:
            self.set_input(vals[0])
            self.app.status("已把这条原文回填到输入框")

    def del_selected(self):
        sel = self.tree.selection()
        if not sel:
            self.app.status("先在记忆里选一行")
            return
        idxs = [self.tree.index(i) for i in sel]
        self.app.t.delete_memory(self.side, idxs)
        self.refresh_memory()
        self.app.status("已从本栏记忆删掉 %d 条" % len(idxs))

    def clear_memory(self):
        self.app.t.clear_memory(self.side)
        self.refresh_memory()
        self.app.status("已清空本栏记忆")

    def copy_selected_src(self):
        sel = self.tree.selection()
        arr = self.app.t.memory(self.side)
        if not sel or not arr:
            return
        i = self.tree.index(sel[0])
        if 0 <= i < len(arr):
            self.app.clipboard_clear()
            self.app.clipboard_append(arr[i].get("src", ""))
            self.app.status("已复制该条原文")


# ───────────────────────── 设置 ─────────────────────────

class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.title("设置 · 自定义服务")
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()
        self.idx = -1

        wrap = ttk.Frame(self, padding=12)
        wrap.pack(fill="both", expand=True)

        left = ttk.Frame(wrap)
        left.grid(row=0, column=0, sticky="ns")
        right = ttk.Frame(wrap)
        right.grid(row=0, column=1, sticky="nsew", padx=(14, 0))

        ttk.Label(left, text="已保存的服务", style="Hint.TLabel").pack(anchor="w")
        self.lst = tk.Listbox(left, height=16, width=22, exportselection=False,
                              font=FONT_SMALL, relief="solid", borderwidth=1,
                              highlightthickness=1, highlightbackground=C_LINE,
                              activestyle="none")
        self.lst.pack(fill="both", expand=True, pady=(4, 6))
        self.lst.bind("<<ListboxSelect>>", self.on_pick)
        b = ttk.Frame(left)
        b.pack(fill="x")
        ttk.Button(b, text="新建", command=self.on_new, width=8).pack(side="left")
        ttk.Button(b, text="删除", command=self.on_del, width=8).pack(side="left", padx=4)

        # —— 语音输入 ——
        voice = ttk.LabelFrame(left, text="语音输入", padding=6)
        voice.pack(fill="x", pady=(12, 0))

        ttk.Label(voice, text="识别后端", style="Hint.TLabel").pack(anchor="w")
        self.v_asr = tk.StringVar(
            value={"sensevoice": "SenseVoice（中文准）",
                   "whisper": "Whisper（多语言稳）"}.get(
                       app.t.config.get("asrBackend", "sensevoice"),
                       "SenseVoice（中文准）"))
        ttk.Combobox(voice, textvariable=self.v_asr, state="readonly", width=20,
                     values=["SenseVoice（中文准）", "Whisper（多语言稳）"]).pack(fill="x")

        ttk.Label(voice, text="麦克风", style="Hint.TLabel").pack(anchor="w", pady=(6, 0))
        devs = list_input_devices()
        self._dev_ids = [None] + [d[0] for d in devs]
        self._dev_labels = ["（系统默认）"] + ["%s" % d[1][:22] for d in devs]
        cur = app.t.config.get("asrDevice")
        self.v_dev = tk.StringVar(
            value=self._dev_labels[self._dev_ids.index(cur)]
            if cur in self._dev_ids else self._dev_labels[0])
        ttk.Combobox(voice, textvariable=self.v_dev, state="readonly", width=20,
                     values=self._dev_labels).pack(fill="x")

        ttk.Label(voice, text="首次说话要先加载模型（约 3 秒）\n"
                              "换个后端要关掉程序重开",
                  style="Hint.TLabel", wraplength=200,
                  justify="left").pack(anchor="w", pady=(6, 0))

        # —— 快捷键（可改）——
        hkf = ttk.LabelFrame(left, text="全局快捷键", padding=6)
        hkf.pack(fill="x", pady=(10, 0))
        try:
            from overlay import hotkey_pair, key_name
            (t_mods, t_vk), (c_mods, c_vk) = hotkey_pair(app)
            self._hk = {"toggle": [t_mods, t_vk], "clip": [c_mods, c_vk]}
        except Exception as e:
            self._hk = {"toggle": list((0, 0x4F)), "clip": list((0, 0x56))}
            ttk.Label(hkf, text="取不到当前键位（%s）" % e,
                      style="Hint.TLabel").pack(anchor="w")
        self._hk_lbl = {}
        for _k, _label in (("toggle", "显示/隐藏悬浮窗"), ("clip", "翻译剪贴板")):
            _row = ttk.Frame(hkf)
            _row.pack(fill="x", pady=(2, 0))
            ttk.Label(_row, text=_label, width=14,
                      style="Hint.TLabel").pack(side="left")
            ttk.Button(_row, text="改", width=4,
                       command=lambda k=_k: self.on_rebind(k)).pack(side="left")
            _lb = ttk.Label(_row, text=key_name(*self._hk[_k]), style="Hint.TLabel")
            _lb.pack(side="left", padx=6)
            self._hk_lbl[_k] = _lb
        ttk.Button(hkf, text="恢复默认",
                   command=self.on_hotkey_default).pack(anchor="w", pady=(6, 0))
        self.lbl_hk = ttk.Label(
            hkf, text="全局生效，其它程序里也能按。\n改完点「保存并关闭」立刻生效，不用重启。",
            style="Hint.TLabel", wraplength=210, justify="left")
        self.lbl_hk.pack(anchor="w", pady=(4, 0))

        def field(label, widget):
            ttk.Label(right, text=label, style="Hint.TLabel").pack(anchor="w", pady=(8, 2))
            widget.pack(fill="x")

        self.v_name = tk.StringVar()
        self.v_base = tk.StringVar(value="https://api.deepseek.com")
        self.v_key = tk.StringVar()
        self.v_model = tk.StringVar()
        self.v_proxy = tk.BooleanVar(value=False)

        field("名称", ttk.Entry(right, textvariable=self.v_name, width=48))
        field("Base URL（OpenAI 兼容）", ttk.Entry(right, textvariable=self.v_base, width=48))

        ttk.Label(right, text="API Key", style="Hint.TLabel").pack(anchor="w", pady=(8, 2))
        kf = ttk.Frame(right)
        kf.pack(fill="x")
        self.e_key = ttk.Entry(kf, textvariable=self.v_key, width=40, show="*")
        self.e_key.pack(side="left", fill="x", expand=True)
        self.v_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text="显示", variable=self.v_show,
                        command=self.toggle_show).pack(side="left", padx=6)

        ttk.Label(right, text="模型", style="Hint.TLabel").pack(anchor="w", pady=(8, 2))
        mf = ttk.Frame(right)
        mf.pack(fill="x")
        self.cb_model = ttk.Combobox(mf, textvariable=self.v_model, width=32)
        self.cb_model.pack(side="left", fill="x", expand=True)
        ttk.Button(mf, text="读取模型", command=self.on_models, width=10).pack(side="left", padx=6)

        ttk.Checkbutton(right, text="走本地代理 127.0.0.1:7890（OpenAI 等需要时勾上）",
                        variable=self.v_proxy).pack(anchor="w", pady=(10, 0))

        self.lbl_tip = ttk.Label(right, text="填好 Base URL 和 Key，点「读取模型」，选一个。",
                                 style="Hint.TLabel", wraplength=380, justify="left")
        self.lbl_tip.pack(anchor="w", pady=(10, 0))

        bb = ttk.Frame(right)
        bb.pack(fill="x", pady=(12, 0))
        ttk.Button(bb, text="测试", command=self.on_test, width=10).pack(side="left")
        ttk.Button(bb, text="保存并关闭", command=self.on_save, width=14).pack(side="left", padx=6)
        ttk.Button(bb, text="取消", command=self.destroy, width=10).pack(side="left")

        self.refresh_list()

    def toggle_show(self):
        self.e_key.configure(show="" if self.v_show.get() else "*")

    # 设置里那个"启动时检查新版本"开关用的（前端重做时接上它）
    def set_check_updates(self, on):
        self.t.config["checkUpdates"] = bool(on)
        self.t.save_config()

    def providers(self):
        return self.t.config.get("providers", [])

    def refresh_list(self):
        self.lst.delete(0, "end")
        for p in self.providers():
            self.lst.insert("end", p.get("name", "?"))

    def on_pick(self, _e=None):
        sel = self.lst.curselection()
        if not sel:
            return
        self.idx = sel[0]
        p = self.providers()[self.idx]
        self.v_name.set(p.get("name", ""))
        self.v_base.set(p.get("baseUrl", ""))
        self.v_key.set(p.get("apiKey", ""))
        self.v_model.set(p.get("model", ""))
        self.v_proxy.set(bool(p.get("useProxy", False)))
        self.cb_model["values"] = [p.get("model", "")] if p.get("model") else []

    def on_new(self):
        self.idx = -1
        self.lst.selection_clear(0, "end")
        self.v_name.set("")
        self.v_base.set("https://api.deepseek.com")
        self.v_key.set("")
        self.v_model.set("")
        self.v_proxy.set(False)
        self.cb_model["values"] = []
        self.lbl_tip.configure(text="新建：填 Base URL 和 Key，点「读取模型」，选一个。")

    def on_del(self):
        sel = self.lst.curselection()
        if not sel:
            self.lbl_tip.configure(text="先在上面选一个。")
            return
        self.t.delete_provider(self.providers()[sel[0]].get("name"))
        self.idx = -1
        self.refresh_list()
        self.on_new()
        self.app.refresh_backends()

    def on_models(self):
        self.lbl_tip.configure(text="读取中…")
        self.update_idletasks()
        try:
            ids = self.t.probe_models(self.v_base.get(), self.v_key.get(), self.v_proxy.get())
            self.cb_model["values"] = ids
            if ids:
                self.v_model.set(ids[0])
            self.lbl_tip.configure(text="读到 %d 个：%s" % (len(ids), ", ".join(ids[:6])))
        except Exception as e:
            self.lbl_tip.configure(text="读取失败：%s" % e)

    def on_test(self):
        self.lbl_tip.configure(text="测试中…")
        self.update_idletasks()
        try:
            r = self.t.probe_chat(self.v_base.get(), self.v_key.get(),
                                  self.v_model.get(), self.v_proxy.get())
            self.lbl_tip.configure(text="测试通过：" + r["text"][:120])
        except Exception as e:
            self.lbl_tip.configure(text="测试失败：%s" % e)

    # ── 快捷键编辑 ──

    def on_rebind(self, which):
        """改一个键：勾修饰键 + 选按键，选定后立刻试注册，冲突当场报。"""
        from overlay import (probe_hotkey, key_name, MOD_ALT, MOD_CONTROL,
                             MOD_SHIFT, MOD_WIN, HOTKEY_KEYS)
        dlg = tk.Toplevel(self)
        dlg.title("改快捷键")
        dlg.transient(self)
        dlg.resizable(False, False)

        _mods0, _vk0 = self._hk[which]
        pairs = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT),
                 ("Shift", MOD_SHIFT), ("Win", MOD_WIN))
        vs = {n: tk.BooleanVar(value=bool(_mods0 & m)) for n, m in pairs}

        row = ttk.Frame(dlg, padding=10)
        row.pack(fill="x")
        for n, _m in pairs:
            ttk.Checkbutton(row, text=n, variable=vs[n]).pack(side="left")
        vk = tk.StringVar(value=key_name(0, _vk0))
        ttk.Combobox(row, textvariable=vk, state="readonly", width=6,
                     values=[k[0] for k in HOTKEY_KEYS]).pack(side="left", padx=8)

        msg = ttk.Label(dlg, text="勾上至少一个修饰键，再选一个按键。",
                        style="Hint.TLabel", wraplength=320, justify="left")
        msg.pack(anchor="w", padx=10)

        def mods_now():
            m = 0
            for n, bit in pairs:
                if vs[n].get():
                    m |= bit
            return m

        def vk_now():
            for name, code in HOTKEY_KEYS:
                if name == vk.get():
                    return code
            return None

        def try_it():
            m, v = mods_now(), vk_now()
            if v is None:
                msg.configure(text="先选一个按键。")
                return
            good, why = probe_hotkey(m, v)
            if not good:
                msg.configure(text="用不了：%s —— 换一个" % why)
                return
            self._hk[which] = [m, v]
            self._hk_lbl[which].configure(text=key_name(m, v))
            self.lbl_hk.configure(
                text="已改成 %s —— 点「保存并关闭」生效。" % key_name(m, v))
            dlg.destroy()

        bb = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        bb.pack(fill="x")
        ttk.Button(bb, text="测试并采用", command=try_it).pack(side="left")
        ttk.Button(bb, text="取消", command=dlg.destroy).pack(side="left", padx=6)
        dlg.grab_set()

    def on_hotkey_default(self):
        from overlay import DEFAULT_TOGGLE, DEFAULT_CLIP, key_name
        self._hk["toggle"] = list(DEFAULT_TOGGLE)
        self._hk["clip"] = list(DEFAULT_CLIP)
        for k in ("toggle", "clip"):
            self._hk_lbl[k].configure(text=key_name(*self._hk[k]))
        self.lbl_hk.configure(text="已恢复默认 —— 点「保存并关闭」生效。")

    def save_hotkeys(self):
        """写进 config 并当场重新注册（不用重启）。"""
        from overlay import apply_hotkeys
        self.t.config["hotkeyToggle"] = list(self._hk["toggle"])
        self.t.config["hotkeyClipboard"] = list(self._hk["clip"])
        self.t.save_config()
        good, info = apply_hotkeys(self.app)
        self.lbl_hk.configure(text=("快捷键已生效：%s" % info) if good
                              else ("装不上：%s" % info))

    def save_voice(self):
        self.t.config["asrBackend"] = ("sensevoice"
                                       if self.v_asr.get().startswith("SenseVoice")
                                       else "whisper")
        dev = None
        try:
            dev = self._dev_ids[self._dev_labels.index(self.v_dev.get())]
        except Exception:
            dev = None
        self.t.config["asrDevice"] = dev
        self.t.save_config()
        self.app.recorder.device = dev

    def on_save(self):
        self.save_voice()
        self.save_hotkeys()
        name = self.v_name.get().strip()
        if not name:
            self.lbl_tip.configure(text="名称不能空。")
            return
        self.t.upsert_provider({
            "name": name,
            "baseUrl": self.v_base.get().strip(),
            "apiKey": self.v_key.get().strip(),
            "model": self.v_model.get().strip(),
            "useProxy": bool(self.v_proxy.get()),
        })
        self.app.refresh_backends()
        self.refresh_list()
        self.lbl_tip.configure(text="已保存。")


# ───────────────────────── 主窗口 ─────────────────────────

class App(tk.Tk):
    def __init__(self):
        # 源码运行时也使用自己的任务栏身份，避免沿用 Python 的图标。
        try:
            set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            set_id.argtypes = [ctypes.c_wchar_p]
            set_id.restype = ctypes.c_long
            set_id("NeoHotaru.PretendForeigner.Translator")
        except (AttributeError, OSError):
            pass
        super().__init__()
        apply_app_icon(self)
        setup_style(self)
        self.title(WINDOW_TITLE)
        self.configure(bg=C_BG)

        self.t = Translator()                 # ← 后端全在这里
        self.backend_keys = []
        self.busy = 0
        self._say_queue = queue.Queue()

        # 语音输入
        self.recorder = Recorder(device=self.t.config.get("asrDevice"))
        self.asr = AsrClient(backend=self._asr_backend())
        self.recording_target = None
        self._rec_id = None
        self._rec_t0 = 0.0
        self._shown_level = 0.0

        self._build_ui()
        self.refresh_backends()
        self.load_session_into_ui()
        self._restore_geometry()

        # 公开版本没有预置 key，别人第一次打开要先选引擎。
        # 本机已经有 key 的话这个调用会直接返回，不会弹窗。
        self._run_setup_if_needed()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pump_id = self.after(120, self._pump)

        # 窗口内快捷键：Ctrl+Alt+1 / +2 开录，Esc 取消
        self.bind("<Control-Alt-Key-1>", lambda e: self.toggle_voice(self.lane_mine))
        self.bind("<Control-Alt-Key-2>", lambda e: self.toggle_voice(self.lane_peer))
        self.bind("<Escape>", lambda e: self.cancel_recording())

        # 启动 3 秒后在后台把识别模型加载好，第一次点麦克风就不用等
        self.overlay = None
        self.hotkeys = None
        if self.t.config.get("asrWarmup", True):
            self._warm_id = self.after(3000, lambda: self.asr.warm_up())
        if self.t.config.get("globalHotkeys", True):
            self._hk_id = self.after(500, self._install_hotkeys)

        # 悄悄问一次有没有新版本。后台线程，失败只写日志、不打扰用户。
        # ⚠ 必须待在 __init__ 里。踩过:上一版误放进 _run_setup_if_needed()，
        #   而那个方法第一句是 "if not needs_setup(): return" ——
        #   于是所有已经配好引擎的机器（也就是全部老用户）永远走不到这一步，
        #   日志里从来没有 update 那一行。
        if self.t.config.get("checkUpdates", True):
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _run_setup_if_needed(self):
        """公开版本第一次运行时弹向导，逼用户先选一个翻译引擎。

        ⚠️ 必须先 deiconify + update 把主窗口真正映射出来：
        向导是主窗口的 transient 子窗口，父窗口没映射时子窗口**不会显示**
        （实测 withdraw 状态下 winfo_ismapped()=0、尺寸停在 1x1）。
        """
        try:
            from setup_wizard import maybe_run
        except Exception as e:
            log("setup_wizard import failed: %r" % e)
            return
        if not self.t.needs_setup():
            return
        self.deiconify()
        self.update()               # 让主窗口先映射，否则向导不会显示
        try:
            if not maybe_run(self):
                self.destroy()
                raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            log("setup wizard failed: %r" % e)
            return
        self.refresh_backends()
        self.load_session_into_ui()

    def _check_updates(self):
        """只在新版真的存在时提示。线程里拿结果，回主线程改控件。"""
        try:
            from translator_core import check_latest_release
            newer, tag, url = check_latest_release()
            # 无论成败都写一行 —— 否则"请求失败"和"没有新版"在日志里长得一样，
            # 用户没法判断到底是哪种（我因此给过错误的排查指引）。
            log("update check: newer=%s tag=%s url=%s" % (newer, tag, url))
            if newer and tag:
                self.after(0, lambda: self.status(
                    "有新版本 %s —— %s" % (tag, url or "见项目主页的 Releases")))
        except Exception as e:
            log("update check failed: %r" % e)

    def _install_hotkeys(self):
        try:
            from overlay import install_hotkeys, hotkey_line
            self.hotkeys = install_hotkeys(self)
            bad = self.hotkeys.failed
            if bad:
                self.status("快捷键没装上：" + "；".join(
                    "%s → %s" % (v[0], v[2]) for v in bad.values()))
            else:
                # 不写死键名：实际注册的键来自 config，这里必须显示同一份来源。
                # 踩过：键位从 Ctrl+Alt 换成 Win+Alt 后，这行字没改，界面一直报旧键。
                self.status("快捷键就绪：" + hotkey_line(self))
        except Exception as e:
            log("hotkey install failed: %r" % e)

    # ── 状态栏（线程安全：走队列，只有主线程碰控件）──

    def status(self, text, kind="info"):
        self._say_queue.put((text, kind))

    def _pump(self):
        try:
            while True:
                text, kind = self._say_queue.get_nowait()
                self.lbl_status.configure(
                    text=text,
                    foreground={"info": "#4b5563", "ok": C_OK, "bad": C_BAD}.get(kind, "#4b5563"))
        except queue.Empty:
            pass
        except Exception:
            return                      # 窗口正在销毁，别再排下一次
        self._pump_id = self.after(120, self._pump)

    # ── 界面 ──

    def _build_ui(self):
        self.minsize(1120, 740)
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, style="Side.TFrame", width=230, padding=(20, 24))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = ttk.Frame(sidebar, style="Side.TFrame")
        brand.pack(fill="x")
        tk.Label(brand, image=self._app_icon_images[0], bg=C_SIDEBAR).pack(side="left", padx=(0, 8))
        ttk.Label(brand, text="假装外国人", style="Side.TLabel",
                  font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        ttk.Label(sidebar, text="把话说成你的样子", style="SideHint.TLabel").pack(
            anchor="w", pady=(6, 30))

        ttk.Label(sidebar, text="当前会话", style="Side.TLabel").pack(anchor="w")
        self.cb_sess = ttk.Combobox(sidebar, width=16, state="readonly")
        self.cb_sess.pack(fill="x", pady=(8, 8))
        self.cb_sess.bind("<<ComboboxSelected>>", self.on_switch_session)
        ttk.Button(sidebar, text="新建会话", command=self.on_new_session).pack(fill="x")
        row = ttk.Frame(sidebar, style="Side.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="重命名", style="Side.TButton", command=self.on_rename_session).pack(side="left")
        ttk.Button(row, text="删除", style="Side.TButton", command=self.on_del_session).pack(side="right")

        ttk.Separator(sidebar).pack(fill="x", pady=22)
        ttk.Label(sidebar, text="语境与术语", style="Side.TLabel").pack(anchor="w")
        self.v_note = tk.StringVar()
        note = ttk.Entry(sidebar, textvariable=self.v_note)
        note.pack(fill="x", pady=(8, 8))
        note.bind("<FocusOut>", lambda e: self.on_note_change())
        note.bind("<Return>", lambda e: self.on_note_change())
        ttk.Label(sidebar, text="例如：埋点 = event tracking\n仅用于当前会话", style="SideHint.TLabel",
                  justify="left", wraplength=190).pack(anchor="w")
        self.v_depth = tk.StringVar()
        self.v_budget = tk.StringVar()
        self.v_cross = tk.StringVar()
        ttk.Button(sidebar, text="调整上下文记忆…", style="Side.TButton",
                   command=self.open_context_settings).pack(fill="x", pady=(12, 0))

        bottom = ttk.Frame(sidebar, style="Side.TFrame")
        bottom.pack(side="bottom", fill="x")
        ttk.Label(bottom, text="翻译引擎", style="Side.TLabel").pack(anchor="w")
        self.cb_backend = ttk.Combobox(bottom, width=16, state="readonly")
        self.cb_backend.pack(fill="x", pady=(8, 8))
        self.cb_backend.bind("<<ComboboxSelected>>", self.on_backend_change)
        self.lbl_engine = ttk.Label(bottom, text="", style="SideHint.TLabel", wraplength=190,
                                    justify="left")
        self.lbl_engine.pack(anchor="w", pady=(0, 10))
        ttk.Button(bottom, text="引擎与应用设置", command=self.open_settings).pack(fill="x")

        workspace = ttk.Frame(shell, padding=(24, 22, 24, 14))
        workspace.pack(side="left", fill="both", expand=True)
        heading = ttk.Frame(workspace)
        heading.pack(fill="x")
        ttk.Button(heading, text="打开悬浮窗", command=self.toggle_overlay).pack(side="right")
        ttk.Label(heading, text="双向翻译", style="Title.TLabel").pack(side="left")
        ttk.Label(workspace, text="两边各记各的话，延续各自的表达习惯。",
                  style="Hint.TLabel").pack(anchor="w", pady=(5, 20))

        controls = ttk.Frame(workspace)
        controls.pack(fill="x", pady=(0, 18))
        for col in (0, 2):
            controls.columnconfigure(col, weight=1)
        my = ttk.Frame(controls)
        my.grid(row=0, column=0, sticky="ew")
        ttk.Label(my, text="我的语言", style="Hint.TLabel").pack(anchor="w", pady=(0, 6))
        self.cb_mine = ttk.Combobox(my, width=16, state="readonly", values=[n for _, n in LANGS])
        self.cb_mine.pack(fill="x")
        self.cb_mine.bind("<<ComboboxSelected>>", lambda e: self.on_langs_change())
        ttk.Label(controls, text="⇄", foreground=C_MUTED, font=("Segoe UI", 18)).grid(
            row=0, column=1, padx=16, pady=(20, 0))
        peer = ttk.Frame(controls)
        peer.grid(row=0, column=2, sticky="ew")
        ttk.Label(peer, text="对方语言", style="Hint.TLabel").pack(anchor="w", pady=(0, 6))
        self.cb_peer = ttk.Combobox(peer, width=16, state="readonly", values=[n for _, n in LANGS])
        self.cb_peer.pack(fill="x")
        self.cb_peer.bind("<<ComboboxSelected>>", lambda e: self.on_langs_change())
        mode = ttk.Frame(controls)
        mode.grid(row=0, column=3, sticky="ew", padx=(24, 0))
        ttk.Label(mode, text="表达语气", style="Hint.TLabel").pack(anchor="w", pady=(0, 6))
        self.cb_mode = ttk.Combobox(mode, width=13, state="readonly",
                                   values=["自动判断", "精确 precise", "闲聊 casual"])
        self.cb_mode.pack(fill="x")
        self.cb_mode.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        self.paned = ttk.PanedWindow(workspace, orient="horizontal")
        self.paned.pack(fill="both", expand=True)
        self.lane_mine = Lane(self.paned, "toPeer", C_MINE,
                              self.on_translate_mine, self.on_copy_mine,
                              lambda: self.toggle_voice(self.lane_mine), self)
        self.lane_peer = Lane(self.paned, "fromPeer", C_PEER,
                              self.on_translate_peer, self.on_copy_peer,
                              lambda: self.toggle_voice(self.lane_peer), self)
        self.paned.add(self.lane_mine, weight=1)
        self.paned.add(self.lane_peer, weight=1)

        foot = ttk.Frame(workspace)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(foot, text="交换内容", style="Quiet.TButton",
                   command=self.on_swap_sides).pack(side="right")
        ttk.Button(foot, text="清空两栏", style="Quiet.TButton",
                   command=self.on_clear_both).pack(side="right", padx=(0, 6))
        self.lbl_status = ttk.Label(foot, text="就绪", style="Status.TLabel",
                                    wraplength=620, justify="left")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        foot.bind("<Configure>", lambda e: self.lbl_status.configure(
            wraplength=max(260, e.width - 230)))
        # 先给状态栏留位置，再让编辑区占据剩余空间。
        self.paned.pack_forget()
        self.paned.pack(fill="both", expand=True)
        self.paned.bind("<ButtonRelease-1>", lambda e: self._limit_sash())

    def open_context_settings(self):
        existing = getattr(self, "context_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = self.context_dialog = tk.Toplevel(self)
        dialog.title("上下文记忆")
        dialog.configure(bg=C_BG)
        dialog.transient(self)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="上下文记忆", style="Head.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(body, text="两条记忆线分别保留自己的用词与语气。",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 18))
        fields = [("每侧带入的记忆条数", self.v_depth, MEM_MIN, MEM_MAX, self.on_depth_change),
                  ("上下文字数上限（千字）", self.v_budget, BUDGET_MIN // BUDGET_STEP,
                   BUDGET_MAX // BUDGET_STEP, self.on_budget_change),
                  ("参照对方最近几条", self.v_cross, 0, 20, self.on_cross_change)]
        for row, (label, variable, low, high, callback) in enumerate(fields, 2):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=7)
            spin = ttk.Spinbox(body, from_=low, to=high, textvariable=variable,
                               width=7, command=callback)
            spin.grid(row=row, column=1, padx=(24, 0), pady=7)
            spin.bind("<FocusOut>", lambda e, c=callback: c())
            spin.bind("<Return>", lambda e, c=callback: c())
        ttk.Label(body, text="参照对方只用于理解指代；设为 0 可关闭。\n免费机翻不使用上下文和术语。",
                  style="Hint.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(16, 20))
        def finish():
            self.on_depth_change()
            self.on_budget_change()
            self.on_cross_change()
            self.sync_views()
            dialog.destroy()
        ttk.Button(body, text="完成", style="Go.TButton", command=finish).grid(
            row=6, column=1, sticky="e")
        dialog.protocol("WM_DELETE_WINDOW", finish)
        dialog.bind("<Escape>", lambda e: finish())

    def _restore_geometry(self):
        cfg = self.t.config
        try:
            self.geometry(cfg.get("windowGeometry") or DEFAULT_GEOMETRY)
        except Exception:
            self.geometry(DEFAULT_GEOMETRY)

        # 分栏位置必须等窗口真正映射、paned 有了真实宽度之后再设。
        # 之前在 __init__ 里直接设：那时 paned 宽度还是 1 像素，
        # sashpos 会被夹成 0，等窗口显示出来左栏就只剩 1 像素宽了。
        try:
            self._want_sash = int(cfg.get("paneSash"))
        except Exception:
            self._want_sash = None
        self._sash_tries = 0
        self.bind("<Map>", lambda e: self.after(80, self._apply_sash), add="+")

    def _apply_sash(self):
        """把分栏线放到保存的位置；窗口还没量好就再等一会儿。"""
        w = self.paned.winfo_width()
        if w <= 50:
            self._sash_tries += 1
            if self._sash_tries < 25:
                self.after(80, self._apply_sash)
            return

        # 两栏都留出容纳常用操作的宽度，其余位置回到正中间。
        # 存的值超出当前宽度、或分栏线被拖到边上，都在这里兜住。
        lo, hi = min(360, w // 2), max(w - 360, w // 2)
        want = self._want_sash
        if want is None or want < lo or want > hi:
            want = w // 2
        try:
            self.paned.sashpos(0, want)
        except Exception:
            pass

    def _limit_sash(self):
        w = self.paned.winfo_width()
        if w > 50:
            self.paned.sashpos(0, max(min(360, w // 2),
                min(self.paned.sashpos(0), max(w - 360, w // 2))))

    # ── 后端 ──

    def refresh_backends(self):
        items = self.t.backends()
        self.backend_keys = [k for _, k in items]
        self.cb_backend["values"] = [n for n, _ in items]
        want = self.t.active_backend()
        self.cb_backend.current(self.backend_keys.index(want)
                                if want in self.backend_keys else 0)
        self._refresh_engine_hint()

    def _refresh_engine_hint(self):
        if self.t.active_backend() == "google":
            self.lbl_engine.configure(text="需能访问 Google\n不使用语气、记忆或术语")
        else:
            self.lbl_engine.configure(text="使用当前会话的语境与记忆")

    def on_backend_change(self, _e=None):
        i = self.cb_backend.current()
        if 0 <= i < len(self.backend_keys):
            self.t.set_backend(self.backend_keys[i])
            self._refresh_engine_hint()

    def on_mode_change(self):
        self.t.set_mode(MODE_CODES[self.cb_mode.current()])

    def on_langs_change(self):
        self.t.set_langs(CODE_OF_LABEL.get(self.cb_mine.get(), "zh"),
                         CODE_OF_LABEL.get(self.cb_peer.get(), "en"))
        self.update_lane_titles()

    def on_depth_change(self):
        d = clamp_depth(self.v_depth.get())
        self.v_depth.set(str(d))
        self.t.set_memory(depth=d)

    def on_budget_change(self):
        try:
            b = int(str(self.v_budget.get()).strip()) * BUDGET_STEP
        except Exception:
            b = 12000
        b = clamp_budget(b)
        self.v_budget.set(str(b // BUDGET_STEP))
        self.t.set_memory(budget=b)

    def on_cross_change(self):
        try:
            d = int(str(self.v_cross.get()).strip())
        except Exception:
            d = 2
        d = max(0, min(20, d))
        self.v_cross.set(str(d))
        self.t.set_memory(cross=d)

    def on_note_change(self):
        self.t.set_note(self.v_note.get())

    def update_lane_titles(self):
        cfg = self.t.config
        mine = lang_name(cfg.get("myLang", "zh"))
        peer = lang_name(cfg.get("peerLang", "en"))
        self.lane_mine.set_title("我  →  对方")
        self.lane_peer.set_title("对方  →  我")
        self.lane_mine.set_pair("%s → %s" % (mine, peer))
        self.lane_peer.set_pair("%s → %s" % (peer, mine))

    # ── 会话 ──

    def load_session_into_ui(self):
        self.cb_sess["values"] = self.t.session_names()
        self.cb_sess.set(self.t.active)
        self.v_note.set(self.t.note())
        self.lane_mine.refresh_memory()
        self.lane_peer.refresh_memory()
        self.lane_mine.clear_all()
        self.lane_peer.clear_all()
        self.update_lane_titles()
        cfg = self.t.config
        self.cb_mine.set(lang_name(cfg.get("myLang", "zh")))
        self.cb_peer.set(lang_name(cfg.get("peerLang", "en")))
        self.cb_mode.current(MODE_CODES.index(cfg.get("mode", "auto")))
        self.v_depth.set(str(clamp_depth(cfg.get("memoryDepth"))))
        self.v_budget.set(str(clamp_budget(cfg.get("contextCharBudget")) // BUDGET_STEP))
        self.v_cross.set(str(clamp_depth(cfg.get("crossMemoryDepth", 2), 2)))

    def on_switch_session(self, _e=None):
        self.t.switch_session(self.cb_sess.get())
        self.load_session_into_ui()
        self.status("已切到会话「%s」" % self.t.active)

    def on_new_session(self):
        name = simpledialog.askstring("新建会话", "会话名（一般写 Claude 那边的任务名）：",
                                      parent=self)
        if not name:
            return
        if not self.t.add_session(name.strip()):
            messagebox.showwarning("重名", "已经有同名会话了。", parent=self)
            return
        self.load_session_into_ui()
        self.status("已新建会话「%s」" % self.t.active, "ok")

    def on_rename_session(self):
        new = simpledialog.askstring("重命名", "新名字：", initialvalue=self.t.active, parent=self)
        if not new:
            return
        self.t.rename_session(self.t.active, new.strip())
        self.load_session_into_ui()

    def on_del_session(self):
        if len(self.t.sessions) <= 1:
            messagebox.showinfo("不能删", "至少留一个会话。", parent=self)
            return
        if not messagebox.askyesno("删除会话",
                                   "删掉「%s」以及它的两条记忆线？" % self.t.active,
                                   parent=self):
            return
        self.t.delete_session(self.t.active)
        self.load_session_into_ui()
        self.status("已删除", "bad")

    # ── 语音 ──

    def _asr_backend(self):
        b = self.t.config.get("asrBackend")
        return b if b in ("sensevoice", "whisper") else None

    def toggle_voice(self, lane):
        if self.recording_target is lane:
            self.stop_recording()
        elif self.recording_target is not None:
            self.status("正在录另一栏，先停掉那边")
        else:
            self.start_recording(lane)

    def start_recording(self, lane):
        if self.recording_target is not None:
            return
        self.recorder.device = self.t.config.get("asrDevice")
        try:
            self.recorder.start()
        except Exception as e:
            self.status("打不开麦克风：%s" % e, "bad")
            return
        self.recording_target = lane
        self._rec_t0 = time.time()
        self._shown_level = 0.0
        lane.set_recording(True, 0.0)
        self.status("录音中… 再点一次结束，Esc 取消")
        self._tick_recording()

    def _tick_recording(self):
        lane = self.recording_target
        if lane is None:
            return
        el = time.time() - self._rec_t0
        # 原始振幅按 dB 映射（线性映射几乎看不见），再做峰值保持让它别抖
        raw = norm_level(self.recorder.level())
        self._shown_level = max(raw, self._shown_level * 0.82)
        lane.set_level(self._shown_level, el, raw)
        self._rec_id = self.after(100, self._tick_recording)

    def cancel_recording(self):
        if self.recording_target is None:
            return
        lane = self.recording_target
        self.recording_target = None
        try:
            self.after_cancel(self._rec_id)
        except Exception:
            pass
        self.recorder.cancel()
        lane.set_recording(False)
        self.status("已取消录音")

    def stop_recording(self):
        lane = self.recording_target
        if lane is None:
            return
        self.recording_target = None
        try:
            self.after_cancel(self._rec_id)
        except Exception:
            pass

        # 静音或过短就别送去识别：识别器会对着静音编内容
        # （实测把静音"听"成了 "그. 그." 这种幻觉文本，塞进输入框就是垃圾）
        peak = self.recorder.max_peak()
        secs = self.recorder.seconds()
        if secs < 0.35:
            self.recorder.cancel()
            lane.set_recording(False)
            self.status("太短了（%.1f 秒），多说几句" % secs, "bad")
            return
        if peak < 0.015:
            self.recorder.cancel()
            lane.set_recording(False)
            self.status("没听到声音（电平 %.3f），检查麦克风或大声点" % peak, "bad")
            return

        # 录音收尾一定要 in finally：stop() 里任何异常都不能把按钮卡在「停止」上。
        # （真踩过：临时目录被外部删掉 -> FileNotFoundError -> 按钮卡死、没有文字）
        wav = None
        err = None
        try:
            wav = self.recorder.stop()
        except Exception as e:
            err = e
        finally:
            lane.set_recording(False)

        if err is not None:
            log("recorder.stop failed: %r" % err)
            self.status("录音收尾失败：%s" % err, "bad")
            return
        if not wav:
            self.status("没录到声音，检查一下麦克风", "bad")
            return

        self.status("识别中…（第一次用要先加载模型，约几秒）")

        def work():
            try:
                text = self.asr.transcribe(wav)
            except Exception as e:
                self.after(0, lambda: self.status("识别失败：%s" % e, "bad"))
            else:
                self.after(0, lambda: self._on_speech(lane, text))

        threading.Thread(target=work, daemon=True).start()

    def _on_speech(self, lane, text):
        if not text:
            self.status("没听清，再说一次？", "bad")
            return
        old = lane.get_input()
        lane.set_input((old + " " + text) if old else text)
        self.status("听到：%s" % text[:60], "ok")

    # ── 翻译 ──

    def translate_lane(self, lane):
        if self.busy:
            self.status("正在翻译，请稍候")
            return
        text = lane.get_input()
        if not text:
            self.status("这一栏还没有内容")
            return

        plan = self.t.plan(text, lane.side)
        self.busy += 1
        lane.set_busy(True)
        self.status("翻译中…（%s / 目标 %s / 记忆 %d 条 · 约 %d 字）"
                    % (plan["backend"], lang_name(plan["target"]),
                       plan["ctx_count"], plan["ctx_chars"]))

        def worker():
            try:
                r = self.t.translate(text, lane.side)
            except Exception as e:
                self.after(0, lambda error=e: (self._finish(lane), self._on_fail(error, lane)))
            else:
                self.after(0, lambda: (self._finish(lane), self._on_done(lane, r)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, lane, r):
        lane.set_output(r["text"])
        mode = {"literal": "机翻", "precise": "精确", "casual": "闲聊", "auto": "自动"}.get(
            r["mode"], r["mode"])
        lane.set_pair("%s → %s  ·  %s" % (lang_name(r["source"]), lang_name(r["target"]),
                                          mode))
        lane.refresh_memory()
        self.sync_views()
        self.clipboard_clear()
        self.clipboard_append(r["text"])
        self.status("译文已复制 · %.1f 秒 · %s → %s" % (
            r["elapsed"], lang_name(r["source"]), lang_name(r["target"])), "ok")

    def _on_fail(self, e, lane=None):
        self.status("失败：%s" % e, "bad")
        if lane is not None and hasattr(lane, "flash"):
            lane.flash("翻译失败：%s" % e)

    def _finish(self, lane):
        self.busy = max(0, self.busy - 1)
        lane.set_busy(False)

    def on_translate_mine(self):
        self.translate_lane(self.lane_mine)

    def on_translate_peer(self):
        self.translate_lane(self.lane_peer)

    def copy_text(self, text):
        if not text:
            self.status("没有可复制的内容")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status("已复制到剪贴板", "ok")

    def on_copy_mine(self):
        self.copy_text(self.lane_mine.get_output())

    def on_copy_peer(self):
        self.copy_text(self.lane_peer.get_output())

    def on_swap_sides(self):
        a = self.lane_mine.get_output()
        b = self.lane_peer.get_output()
        if not a and not b:
            self.status("两栏都还没有译文")
            return
        self.lane_peer.set_input(a)
        self.lane_mine.set_input(b)
        self.status("已把两栏译文互换到对方的输入框")

    def on_clear_both(self):
        self.lane_mine.clear_all()
        self.lane_peer.clear_all()
        self.status("已清空两栏的输入和输出（记忆保留）")

    # ── 悬浮窗 ──

    def toggle_overlay(self):
        if getattr(self, "overlay", None) is None:
            from overlay import OverlayPanel
            self.overlay = OverlayPanel(self, side=self._last_overlay_side())
            self.overlay.protocol("WM_DELETE_WINDOW", self.overlay.close)
        if self.overlay.winfo_viewable():
            self.overlay.hide()
            from overlay import toggle_key_name
            self.status("悬浮窗已隐藏（%s 可再叫出来）" % toggle_key_name(self))
        else:
            self.overlay.show()
            self.overlay.refresh_memory()
            self.status("悬浮岛已显示，点击胶囊展开翻译")

    def _last_overlay_side(self):
        return self.t.config.get("overlaySide", "toPeer")

    def overlay_clipboard(self):
        """快捷键入口：没开悬浮窗就先开，再翻剪贴板。"""
        if getattr(self, "overlay", None) is None or not self.overlay.winfo_viewable():
            self.toggle_overlay()
        self.overlay.translate_clipboard()

    def sync_views(self):
        """任何一边翻完都刷新另一边的显示，免得两边对不上。"""
        try:
            self.lane_mine.refresh_memory()
            self.lane_peer.refresh_memory()
        except Exception:
            pass
        ov = getattr(self, "overlay", None)
        if ov is not None:
            try:
                ov.refresh_memory()
            except Exception:
                pass

    def open_settings(self):
        SettingsDialog(self)

    def on_close(self):
        # 关掉还没跑的定时器，否则销毁后回调触发会报 invalid command name
        for attr in ("_pump_id", "_hk_id", "_warm_id", "_rec_id"):
            try:
                self.after_cancel(getattr(self, attr))
            except Exception:
                pass
        self.cancel_recording()
        try:
            if getattr(self, "overlay", None) is not None:
                self.t.config["overlaySide"] = self.overlay.side
                self.overlay.destroy()
        except Exception:
            pass
        try:
            if getattr(self, "hotkeys", None) is not None:
                self.hotkeys.stop()
        except Exception:
            pass
        try:
            self.asr.stop()
        except Exception:
            pass
        self.t.set_note(self.v_note.get())
        try:
            self.t.config["windowGeometry"] = self.geometry()
            # 只在分栏线处于合理范围时才存，免得把坏值写回去
            w = self.paned.winfo_width()
            pos = self.paned.sashpos(0)
            if w > 50 and int(w * 0.2) <= pos <= int(w * 0.8):
                self.t.config["paneSash"] = pos
        except Exception:
            pass
        self.t.save_all()
        self.destroy()


def main():
    import sys
    # 打包后磁盘上既没有 python 可执行文件、也没有 asr_worker.py（它在 PYZ 里）——
    # 于是让【同一个 exe】用 --asr-worker 把自己当识别工作进程跑。
    # 必须在创建任何 GUI 之前判断，否则会先开出一个窗口。
    if "--asr-worker" in sys.argv:
        import asr_worker
        sys.argv = [a for a in sys.argv if a != "--asr-worker"]
        sys.exit(asr_worker.main())

    from translator_core import log, use_user_data_dir
    # 配置 / 会话放 %APPDATA%（装到 Program Files 也能写）；旁边有旧配置会自动复制过去
    use_user_data_dir()
    log("--- start ---")
    if not single_instance_guard():
        log("another instance is running, focused it and exited")
        return
    App().mainloop()
    log("--- exit ---")


if __name__ == "__main__":
    main()
