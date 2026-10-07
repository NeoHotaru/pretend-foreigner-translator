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

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_HEAD = ("Microsoft YaHei UI", 10, "bold")
FONT_TEXT = ("Microsoft YaHei UI", 10)

# 颜色统一从 ui_kit 取，别各定义一份（改主题只改一个地方）
from ui_kit import (C_BAD, C_BG, C_LINE, C_MINE, C_MUTED,  # noqa: E402
                    C_OK, C_OUT_BG, C_PEER)


def setup_style(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass

    st.configure(".", font=FONT_UI, background=C_BG)
    st.configure("TFrame", background=C_BG)
    st.configure("TLabel", background=C_BG, foreground="#1f2430")
    st.configure("Hint.TLabel", background=C_BG, foreground=C_MUTED, font=FONT_SMALL)
    st.configure("Head.TLabel", background=C_BG, foreground="#1f2430", font=FONT_HEAD)

    st.configure("TButton", padding=(10, 4), font=FONT_SMALL)
    st.map("TButton", background=[("active", "#e8ecf1")])

    st.configure("Go.TButton", padding=(14, 5), font=FONT_UI,
                 foreground="#ffffff", background=C_MINE)
    st.map("Go.TButton",
           background=[("active", "#1d4ed8"), ("disabled", "#a9bce8")],
           foreground=[("disabled", "#eef2ff")])

    st.configure("TEntry", fieldbackground="#ffffff", padding=3)
    st.configure("TCombobox", padding=3)
    st.configure("TSpinbox", padding=3)
    st.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                 rowheight=22, font=FONT_SMALL)
    st.configure("Treeview.Heading", font=FONT_SMALL, padding=(4, 3))
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


# ───────────────────────── 一栏 ─────────────────────────

class Lane(ttk.Frame):
    """一栏：输入 -> 翻译 -> 译文，外加本栏自己的记忆。"""

    def __init__(self, master, side, accent, on_translate, on_copy, on_voice, app):
        super().__init__(master, style="Card.TFrame")
        self.app = app
        self.side = side                      # "toPeer" / "fromPeer"
        self.accent = accent

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        strip = tk.Frame(self, bg=accent)
        strip.grid(row=0, column=0, sticky="ew")
        strip.columnconfigure(1, weight=1)
        self.lbl_title = tk.Label(strip, text="", bg=accent, fg="#ffffff",
                                  font=FONT_HEAD, anchor="w", padx=10, pady=5)
        self.lbl_title.grid(row=0, column=0, sticky="w")
        self.lbl_pair = tk.Label(strip, text="", bg=accent, fg="#e9eefb",
                                 font=FONT_SMALL, anchor="e", padx=10)
        self.lbl_pair.grid(row=0, column=1, sticky="e")

        pad = ttk.Frame(self)
        pad.grid(row=1, column=0, sticky="nsew")
        pad.columnconfigure(0, weight=1)
        pad.rowconfigure(1, weight=5)         # 输入
        pad.rowconfigure(4, weight=5)         # 译文
        pad.rowconfigure(5, weight=0)         # 记忆不参与拉伸

        ttk.Label(pad, text="输入", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 2))
        self.txt_in = PlaceholderText(pad, placeholder="在这里粘贴这一侧要说的话…",
                                      height=7, wrap="word", font=FONT_TEXT,
                                      relief="solid", borderwidth=1, undo=True,
                                      highlightthickness=1, highlightbackground=C_LINE,
                                      highlightcolor=accent)
        self.txt_in.grid(row=1, column=0, sticky="nsew", padx=8)

        bar = ttk.Frame(pad)
        bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 4))
        self.btn_go = ttk.Button(bar, text="翻译", style="Go.TButton",
                                 command=on_translate, width=8)
        self.btn_go.pack(side="left")
        self.btn_mic = ttk.Button(bar, text="🎤 说话", command=on_voice, width=10)
        self.btn_mic.pack(side="left", padx=(6, 4))
        # 喇叭电平表：灰色底座，蓝色从下往上填，只在录音时出现
        self.lvl = tk.Canvas(bar, width=SPEAKER_W, height=SPEAKER_H,
                             highlightthickness=0, bd=0, bg=C_BG)
        self._draw_level(0.0)
        self.btn_copy = ttk.Button(bar, text="复制译文", command=on_copy, width=10)
        self.btn_copy.pack(side="left", padx=4)
        ttk.Button(bar, text="清空", command=self.clear_all, width=6).pack(side="left")
        self.lbl_hint = ttk.Label(bar, text="Ctrl+Enter", style="Hint.TLabel")
        self.lbl_hint.pack(side="right")

        ttk.Label(pad, text="译文", style="Hint.TLabel").grid(
            row=3, column=0, sticky="w", padx=8, pady=(2, 2))
        self.txt_out = tk.Text(pad, height=7, wrap="word", font=FONT_TEXT,
                               relief="solid", borderwidth=1, bg=C_OUT_BG,
                               highlightthickness=1, highlightbackground=C_LINE)
        self.txt_out.grid(row=4, column=0, sticky="nsew", padx=8)
        readonly_text(self.txt_out)

        mem = ttk.Frame(pad)
        mem.grid(row=5, column=0, sticky="nsew", padx=8, pady=(8, 8))
        mem.columnconfigure(0, weight=1)
        mem.rowconfigure(1, weight=0)

        head = ttk.Frame(mem)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.lbl_mem = ttk.Label(head, text="本栏记忆", style="Hint.TLabel")
        self.lbl_mem.pack(side="left")
        ttk.Label(head, text="  双击一行可回填原文", style="Hint.TLabel").pack(side="left")

        cols = ("src", "out", "on")
        self.tree = ttk.Treeview(mem, columns=cols, show="headings",
                                 selectmode="extended", height=6)
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

        mbar = ttk.Frame(mem)
        mbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(mbar, text="删掉选中", command=self.del_selected,
                   width=10).pack(side="left")
        ttk.Button(mbar, text="清空本栏", command=self.clear_memory,
                   width=9).pack(side="left", padx=4)
        ttk.Button(mbar, text="复制选中原文", command=self.copy_selected_src,
                   width=13).pack(side="left")

        self.txt_in.bind("<Control-Return>", lambda e: (on_translate(), "break")[1])

    # — 标题 —

    def set_title(self, text):
        self.lbl_title.configure(text=text)

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
        self.btn_go.configure(state="disabled" if busy else "normal")

    def set_recording(self, on, elapsed=0.0):
        if on:
            self.btn_mic.configure(text="■ 停止")
            self._draw_level(0.0)
            self.lvl.pack(side="left", padx=(0, 2), before=self.btn_copy)
            self.lbl_hint.configure(text="0.0s   Esc 取消")
        else:
            self.btn_mic.configure(text="🎤 说话")
            self._draw_level(0.0)
            try:
                self.lvl.pack_forget()          # 录完收起来，别留个空条
            except Exception:
                pass
            self.lbl_hint.configure(text="Ctrl+Enter")

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

        # —— 快捷键 ——
        hkf = ttk.LabelFrame(left, text="全局快捷键", padding=6)
        hkf.pack(fill="x", pady=(10, 0))
        try:
            from overlay import hotkey_help
            tip = hotkey_help(app)
        except Exception as e:
            tip = "取不到（%s）" % e
        ttk.Label(hkf, text=tip, style="Hint.TLabel",
                  justify="left").pack(anchor="w")
        ttk.Label(hkf, text="全局生效，其它程序里也能按。\n改了要重启程序。",
                  style="Hint.TLabel", wraplength=200,
                  justify="left").pack(anchor="w", pady=(4, 0))

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
        super().__init__()
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

    def _install_hotkeys(self):
        try:
            from overlay import install_hotkeys
            self.hotkeys = install_hotkeys(self)
            bad = self.hotkeys.failed
            if bad:
                self.status("快捷键没装上：" + "；".join(
                    "%s → %s" % (v[0], v[2]) for v in bad.values()))
            else:
                self.status("快捷键就绪：Ctrl+Alt+O 悬浮窗 · Ctrl+Alt+T 翻剪贴板")
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
        head = ttk.Frame(self, padding=(12, 10, 12, 6))
        head.pack(fill="x")

        r1 = ttk.Frame(head)
        r1.pack(fill="x")
        ttk.Label(r1, text="会话", style="Head.TLabel").pack(side="left")
        self.cb_sess = ttk.Combobox(r1, width=20, state="readonly")
        self.cb_sess.pack(side="left", padx=(6, 6))
        self.cb_sess.bind("<<ComboboxSelected>>", self.on_switch_session)
        ttk.Button(r1, text="新建", width=6, command=self.on_new_session).pack(side="left")
        ttk.Button(r1, text="重命名", width=8,
                   command=self.on_rename_session).pack(side="left", padx=3)
        ttk.Button(r1, text="删除", width=6, command=self.on_del_session).pack(side="left")

        ttk.Separator(r1, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(r1, text="后端", style="Head.TLabel").pack(side="left")
        self.cb_backend = ttk.Combobox(r1, width=26, state="readonly")
        self.cb_backend.pack(side="left", padx=(6, 6))
        self.cb_backend.bind("<<ComboboxSelected>>", self.on_backend_change)
        ttk.Button(r1, text="设置", width=6, command=self.open_settings).pack(side="left")
        ttk.Button(r1, text="悬浮窗", width=8,
                   command=self.toggle_overlay).pack(side="left", padx=(4, 0))

        ttk.Separator(r1, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(r1, text="语气", style="Head.TLabel").pack(side="left")
        self.cb_mode = ttk.Combobox(r1, width=13, state="readonly",
                                    values=["自动判断", "精确 precise", "闲聊 casual"])
        self.cb_mode.pack(side="left", padx=(6, 0))
        self.cb_mode.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        r2 = ttk.Frame(head)
        r2.pack(fill="x", pady=(8, 0))

        ttk.Label(r2, text="我的语言").pack(side="left")
        self.cb_mine = ttk.Combobox(r2, width=15, state="readonly",
                                    values=[n for _, n in LANGS])
        self.cb_mine.pack(side="left", padx=(6, 0))
        self.cb_mine.bind("<<ComboboxSelected>>", lambda e: self.on_langs_change())

        ttk.Label(r2, text="对方语言").pack(side="left", padx=(12, 0))
        self.cb_peer = ttk.Combobox(r2, width=15, state="readonly",
                                    values=[n for _, n in LANGS])
        self.cb_peer.pack(side="left", padx=(6, 0))
        self.cb_peer.bind("<<ComboboxSelected>>", lambda e: self.on_langs_change())

        ttk.Separator(r2, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(r2, text="记忆").pack(side="left")
        self.v_depth = tk.StringVar()
        sp = ttk.Spinbox(r2, from_=MEM_MIN, to=MEM_MAX, width=4, textvariable=self.v_depth,
                         command=self.on_depth_change)
        sp.pack(side="left", padx=(6, 2))
        sp.bind("<FocusOut>", lambda e: self.on_depth_change())
        sp.bind("<Return>", lambda e: self.on_depth_change())
        ttk.Label(r2, text="条 /").pack(side="left")

        self.v_budget = tk.StringVar()
        sp2 = ttk.Spinbox(r2, from_=BUDGET_MIN // BUDGET_STEP, to=BUDGET_MAX // BUDGET_STEP,
                          width=4, textvariable=self.v_budget, command=self.on_budget_change)
        sp2.pack(side="left", padx=(4, 2))
        sp2.bind("<FocusOut>", lambda e: self.on_budget_change())
        sp2.bind("<Return>", lambda e: self.on_budget_change())
        ttk.Label(r2, text="千字以内").pack(side="left")

        ttk.Label(r2, text=" / 参照对方").pack(side="left", padx=(8, 0))
        self.v_cross = tk.StringVar()
        sp3 = ttk.Spinbox(r2, from_=0, to=20, width=3, textvariable=self.v_cross,
                          command=self.on_cross_change)
        sp3.pack(side="left", padx=(4, 2))
        sp3.bind("<FocusOut>", lambda e: self.on_cross_change())
        sp3.bind("<Return>", lambda e: self.on_cross_change())
        ttk.Label(r2, text="条").pack(side="left")

        ttk.Separator(r2, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(r2, text="语境 / 术语").pack(side="left")
        self.v_note = tk.StringVar()
        e = ttk.Entry(r2, textvariable=self.v_note)
        e.pack(side="left", fill="x", expand=True, padx=(6, 0))
        e.bind("<FocusOut>", lambda ev: self.on_note_change())
        e.bind("<Return>", lambda ev: self.on_note_change())

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        body = ttk.Frame(self, padding=(12, 10, 12, 6))
        body.pack(fill="both", expand=True)
        self.paned = ttk.PanedWindow(body, orient="horizontal")
        self.paned.pack(fill="both", expand=True)

        self.lane_mine = Lane(self.paned, "toPeer", C_MINE,
                              self.on_translate_mine, self.on_copy_mine,
                              lambda: self.toggle_voice(self.lane_mine), self)
        self.lane_peer = Lane(self.paned, "fromPeer", C_PEER,
                              self.on_translate_peer, self.on_copy_peer,
                              lambda: self.toggle_voice(self.lane_peer), self)
        self.paned.add(self.lane_mine, weight=1)
        self.paned.add(self.lane_peer, weight=1)

        ttk.Separator(self, orient="horizontal").pack(fill="x")
        foot = ttk.Frame(self, padding=(12, 6, 12, 10))
        foot.pack(fill="x")
        self.lbl_status = ttk.Label(foot, text="就绪", style="Status.TLabel")
        self.lbl_status.pack(side="left")
        ttk.Button(foot, text="交换左右内容", width=13,
                   command=self.on_swap_sides).pack(side="right")
        ttk.Button(foot, text="清空输入输出", width=13,
                   command=self.on_clear_both).pack(side="right", padx=6)

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

        # 只接受 20%-80% 之间的值，其余一律回到正中间。
        # 存的值超出当前宽度、或分栏线被拖到边上，都在这里兜住。
        lo, hi = int(w * 0.2), int(w * 0.8)
        want = self._want_sash
        if want is None or want < lo or want > hi:
            want = w // 2
        try:
            self.paned.sashpos(0, want)
        except Exception:
            pass

    # ── 后端 ──

    def refresh_backends(self):
        items = self.t.backends()
        self.backend_keys = [k for _, k in items]
        self.cb_backend["values"] = [n for n, _ in items]
        want = self.t.active_backend()
        self.cb_backend.current(self.backend_keys.index(want)
                                if want in self.backend_keys else 0)

    def on_backend_change(self, _e=None):
        i = self.cb_backend.current()
        if 0 <= i < len(self.backend_keys):
            self.t.set_backend(self.backend_keys[i])

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
                self.after(0, lambda: (self._finish(lane), self._on_fail(e)))
            else:
                self.after(0, lambda: (self._finish(lane), self._on_done(lane, r)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, lane, r):
        lane.set_output(r["text"])
        lane.set_pair("%s → %s  ·  %s" % (lang_name(r["source"]), lang_name(r["target"]),
                                          r["mode"]))
        lane.refresh_memory()
        self.sync_views()
        self.clipboard_clear()
        self.clipboard_append(r["text"])
        self.status("完成 %.1fs · %s→%s / %s · 已复制 · 本栏记忆 %d 条 / %d 字 · 参照对方 %d 条（本栏共 %d 条）"
                    % (r["elapsed"], lang_name(r["source"]), lang_name(r["target"]),
                       r["mode"], r["ctx_count"], r["ctx_chars"], r["cross_count"],
                       r["memory_count"]), "ok")

    def _on_fail(self, e):
        self.status("失败：%s" % e, "bad")

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
            self.overlay.withdraw()
            self.status("悬浮窗已隐藏（Ctrl+Alt+O 可再叫出来）")
        else:
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.refresh_memory()
            self.status("悬浮窗已显示")

    def _last_overlay_side(self):
        return self.t.config.get("overlaySide", "toPeer")

    def overlay_clipboard(self):
        """快捷键入口：没开悬浮窗就先开，再翻剪贴板。"""
        if getattr(self, "overlay", None) is None or not self.overlay.winfo_viewable():
            self.toggle_overlay()
        self.overlay.after(120, self.overlay.translate_clipboard)

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
