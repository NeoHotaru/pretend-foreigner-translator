# -*- coding: utf-8 -*-
"""
setup_wizard.py  —  首次运行向导

为什么要有：公开版本不能带任何预置的 key。别人 clone 下来点开，
必须先自己选一个翻译引擎，否则程序等于空转。

两种情况会弹出来：
    1. 第一次运行（config 里没有 setupDone）
    2. 而且本机确实没有任何能用的自有后端（没找到 DeepSeek key、也没填过自定义服务）

开发机和老用户有 key，永远不会看到这个窗口。

选完之后写 config["setupDone"] = True，不再打扰。
"""

import os
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

from translator_core import ApiError, Translator, list_models
from ui_kit import C_BG, C_LINE, C_MINE, C_MUTED, C_OK

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 12, "bold")

# 常见服务商预设：填好 Base URL，用户只要贴 key
PRESETS = [
    ("DeepSeek（国内直连，便宜）", "https://api.deepseek.com", "deepseek-chat",
     "https://platform.deepseek.com/api_keys"),
    ("硅基流动 SiliconFlow（国内）", "https://api.siliconflow.cn/v1",
     "Qwen/Qwen2.5-72B-Instruct", "https://cloud.siliconflow.cn/account/ak"),
    ("OpenAI（国内需代理）", "https://api.openai.com/v1", "gpt-4o-mini",
     "https://platform.openai.com/api-keys"),
    ("自定义（任何 OpenAI 兼容服务）", "", "", ""),
]

FREE_TEXT = (
    "不用注册、不用填 key，装完就能用。\n"
    "代价：没有语气判定（precise / casual），也不记得上下文，\n"
    "一句话一句话直译。\n"
    "国内需要能访问 Google，否则会连不上。"
)
KEY_TEXT = (
    "质量明显更好：会判语气、会记住上下文、可以填术语表。\n"
    "DeepSeek 国内直连，大约 ¥1 / 百万字。"
)


class SetupWizard(tk.Toplevel):
    """返回 .result: True=配好了，False/None=用户退出了。"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.result = False

        self.title("第一次使用 · 选择翻译引擎")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.on_quit)

        self.v_choice = tk.StringVar(value="google")
        self._build()
        self._sync()

        self.update_idletasks()
        # 摆到主窗口中间
        try:
            px, py = app.winfo_rootx(), app.winfo_rooty()
            pw, ph = app.winfo_width(), app.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry("+%d+%d" % (px + max(0, (pw - w) // 2),
                                      py + max(0, (ph - h) // 3)))
        except Exception:
            pass

        self.grab_set()
        self.focus_force()

    # ── 界面 ──

    def _build(self):
        head = tk.Frame(self, bg=C_MINE)
        head.pack(fill="x")
        tk.Label(head, text="先定一件事：用哪个翻译引擎", bg=C_MINE, fg="white",
                 font=FONT_B, anchor="w", padx=14, pady=10).pack(fill="x")

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, foreground=C_MUTED, font=FONT_S, justify="left",
                  text="跟 Claude / GPT 聊天时，你说中文、它说英文。\n"
                       "这个工具负责两边互译。选好之后可以在「设置」里随时改。"
                  ).pack(anchor="w", pady=(0, 12))

        # ── 选项一：免费机翻 ──
        f1 = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                      highlightbackground=C_LINE)
        f1.pack(fill="x")
        tk.Radiobutton(f1, text="免费机翻", variable=self.v_choice, value="google",
                       bg="#ffffff", font=FONT, activebackground="#ffffff",
                       command=self._sync, padx=8, pady=6, anchor="w"
                       ).pack(fill="x")
        self.lbl_free = tk.Label(f1, text=FREE_TEXT, bg="#ffffff", fg=C_MUTED,
                                 font=FONT_S, justify="left", anchor="w", padx=34)
        self.lbl_free.pack(fill="x", pady=(0, 6))

        # ── 选项二：自己的 key ──
        f2 = tk.Frame(body, bg="#ffffff", highlightthickness=1,
                      highlightbackground=C_LINE)
        f2.pack(fill="x", pady=(10, 0))
        tk.Radiobutton(f2, text="用我自己的 API Key", variable=self.v_choice,
                       value="key", bg="#ffffff", font=FONT,
                       activebackground="#ffffff", command=self._sync,
                       padx=8, pady=6, anchor="w").pack(fill="x")
        tk.Label(f2, text=KEY_TEXT, bg="#ffffff", fg=C_MUTED, font=FONT_S,
                 justify="left", anchor="w", padx=34).pack(fill="x")

        self.kf = tk.Frame(f2, bg="#ffffff")
        self.kf.pack(fill="x", padx=34, pady=(8, 10))

        r0 = tk.Frame(self.kf, bg="#ffffff")
        r0.pack(fill="x")
        tk.Label(r0, text="服务商", bg="#ffffff", font=FONT_S, width=8,
                 anchor="w").pack(side="left")
        self.cb_preset = ttk.Combobox(r0, state="readonly", font=FONT_S,
                                      values=[p[0] for p in PRESETS])
        self.cb_preset.current(0)
        self.cb_preset.pack(side="left", fill="x", expand=True)
        self.cb_preset.bind("<<ComboboxSelected>>", self._on_preset)

        r1 = tk.Frame(self.kf, bg="#ffffff")
        r1.pack(fill="x", pady=(6, 0))
        tk.Label(r1, text="Base URL", bg="#ffffff", font=FONT_S, width=8,
                 anchor="w").pack(side="left")
        self.v_base = tk.StringVar()
        ttk.Entry(r1, textvariable=self.v_base, font=FONT_S).pack(
            side="left", fill="x", expand=True)

        r2 = tk.Frame(self.kf, bg="#ffffff")
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="API Key", bg="#ffffff", font=FONT_S, width=8,
                 anchor="w").pack(side="left")
        self.v_key = tk.StringVar()
        ttk.Entry(r2, textvariable=self.v_key, font=FONT_S, show="*").pack(
            side="left", fill="x", expand=True)

        r3 = tk.Frame(self.kf, bg="#ffffff")
        r3.pack(fill="x", pady=(6, 0))
        tk.Label(r3, text="模型", bg="#ffffff", font=FONT_S, width=8,
                 anchor="w").pack(side="left")
        self.v_model = tk.StringVar()
        self.cb_model = ttk.Combobox(r3, textvariable=self.v_model, font=FONT_S)
        self.cb_model.pack(side="left", fill="x", expand=True)
        ttk.Button(r3, text="读取模型", width=10,
                   command=self.on_fetch_models).pack(side="left", padx=(4, 0))

        r4 = tk.Frame(self.kf, bg="#ffffff")
        r4.pack(fill="x", pady=(6, 0))
        ttk.Button(r4, text="测试连通", width=10,
                   command=self.on_test).pack(side="left")
        ttk.Button(r4, text="去哪里拿 Key", width=14,
                   command=self.on_help).pack(side="left", padx=(6, 0))

        # ── 底部 ──
        self.lbl_msg = ttk.Label(body, text="", foreground=C_MUTED, font=FONT_S,
                                 wraplength=430, justify="left")
        self.lbl_msg.pack(anchor="w", pady=(12, 0))

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="退出", width=10, command=self.on_quit).pack(side="right")
        self.btn_go = ttk.Button(bar, text="开始使用", width=14, command=self.on_ok)
        self.btn_go.pack(side="right", padx=8)

        self._on_preset()
        self.geometry("")

    def _sync(self):
        """选了免费机翻就把 key 那一堆灰掉。"""
        free = (self.v_choice.get() == "google")

        # 注意：ttk.Combobox 继承自 ttk.Entry，
        # 所以下面那个通用循环必须把它排除，否则会把 readonly 覆盖成 normal。
        pairs = ((self.cb_preset, "readonly"), (self.cb_model, "normal"))
        for w, on_state in pairs:
            try:
                w.configure(state=("disabled" if free else on_state))
            except Exception:
                pass

        for child in self.kf.winfo_children():
            for sub in child.winfo_children():
                if isinstance(sub, ttk.Combobox):
                    continue
                if isinstance(sub, (ttk.Entry, ttk.Button)):
                    try:
                        sub.configure(state=("disabled" if free else "normal"))
                    except Exception:
                        pass
        self.lbl_free.configure(fg=(C_OK if free else C_MUTED))

    def _on_preset(self, _e=None):
        i = self.cb_preset.current()
        if 0 <= i < len(PRESETS):
            _, base, model, _url = PRESETS[i]
            self.v_base.set(base)
            if model:
                self.v_model.set(model)
                self.cb_model["values"] = [model]

    def _preset_url(self):
        i = self.cb_preset.current()
        if 0 <= i < len(PRESETS):
            return PRESETS[i][3]
        return ""

    def say(self, msg, color=None):
        self.lbl_msg.configure(text=msg, foreground=color or C_MUTED)
        self.update_idletasks()

    # ── 动作 ──

    def on_help(self):
        url = self._preset_url()
        if url:
            webbrowser.open(url)
            self.say("已打开浏览器：%s" % url)
        else:
            self.say("自定义服务请去服务商的控制台拿 key。")

    def on_fetch_models(self):
        base, key = self.v_base.get().strip(), self.v_key.get().strip()
        if not base or not key:
            self.say("先把 Base URL 和 API Key 填上。", "#b91c1c")
            return
        self.say("读取中…")
        try:
            ids = list_models(base, key)
        except Exception as e:
            self.say("读不到模型列表：%s（也可以直接在「模型」框里手打 id）" % e,
                     "#b91c1c")
            return
        self.cb_model["values"] = ids
        if ids:
            self.v_model.set(ids[0])
        self.say("读到 %d 个模型。" % len(ids), C_OK)

    def on_test(self):
        base, key, model = (self.v_base.get().strip(), self.v_key.get().strip(),
                            self.v_model.get().strip())
        if not (base and key and model):
            self.say("Base URL / API Key / 模型 都要填。", "#b91c1c")
            return
        self.say("测试中…")
        try:
            self.t.probe_chat(base, key, model)
        except Exception as e:
            self.say("测试失败：%s" % e, "#b91c1c")
            return
        self.say("通了，可以点「开始使用」。", C_OK)

    def on_ok(self):
        if self.v_choice.get() == "google":
            self.t.config["activeBackend"] = "google"
            self.t.config["setupDone"] = True
            self.t.save_config()
            self.result = True
            self.destroy()
            return

        base, key, model = (self.v_base.get().strip(), self.v_key.get().strip(),
                            self.v_model.get().strip())
        if not base:
            self.say("填一下 Base URL。", "#b91c1c")
            return
        if not key:
            self.say("填一下 API Key。", "#b91c1c")
            return
        if not model:
            self.say("选一个模型（或点「读取模型」）。", "#b91c1c")
            return

        name = self.cb_preset.get().split("（")[0].strip() or "自定义"
        self.t.upsert_provider({"name": name, "baseUrl": base, "apiKey": key,
                                "model": model, "useProxy": False})
        self.t.config["activeBackend"] = "provider:" + name
        self.t.config["setupDone"] = True
        self.t.save_config()
        self.result = True
        self.destroy()

    def on_quit(self):
        if messagebox.askyesno(
                "还没选翻译引擎",
                "没有翻译引擎就用不了。现在退出吗？\n\n"
                "（下次打开还会问你）", parent=self):
            self.result = False
            self.destroy()


def maybe_run(app):
    """在 App 启动流程里调。返回 True 表示可以继续跑。

    测试用环境变量 PFT_SKIP_SETUP=1 绕过。
    """
    if os.environ.get("PFT_SKIP_SETUP"):
        return True
    if not app.t.needs_setup():
        return True

    w = SetupWizard(app)
    app.wait_window(w)
    return bool(w.result)
