# -*- coding: utf-8 -*-
"""
selftest.py  —  一条命令跑完所有回归

    python selftest.py            全跑（含真实 API 调用，约 15 秒）
    python selftest.py --offline   跳过需要联网/麦克风/模型的部分

改完代码先跑这个。它不依赖具体界面实现，能立刻分清是后端坏了还是前端坏了。
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
if not os.path.isdir(SRC):
    SRC = HERE                      # 也允许直接放在源码目录里跑
sys.path.insert(0, SRC)

PASS, FAIL, SKIP = [], [], []


def ok(name, extra=""):
    PASS.append(name)
    print("  [OK]   %s%s" % (name, ("  " + extra) if extra else ""))


def bad(name, why=""):
    FAIL.append((name, why))
    print("  [FAIL] %s%s" % (name, ("  → " + str(why)) if why else ""))


def skip(name, why=""):
    SKIP.append(name)
    print("  [skip] %s%s" % (name, ("  (" + why + ")") if why else ""))


def section(t):
    print()
    print("=" * 68)
    print("  " + t)
    print("=" * 68)


# ───────────────────────── 1. 纯逻辑 ─────────────────────────

def test_pure():
    section("1. 纯逻辑（不联网、不开窗口）")

    import translator_core as C

    # 语言表
    if len(C.LANGS) >= 19 and C.lang_name("ja") == "日本語":
        ok("语言表", "%d 种" % len(C.LANGS))
    else:
        bad("语言表", len(C.LANGS))

    # 夹取
    cases = [("5", 5), ("0", 0), ("200", 200), ("999", 200), ("-3", 0),
             ("abc", 8), ("", 8), (None, 8)]
    wrong = [(v, got) for v, want in cases
             for got in [C.clamp_depth(v)] if got != want]
    if not wrong:
        ok("clamp_depth 边界")
    else:
        bad("clamp_depth 边界", wrong)

    if C.clamp_budget(500) == 1000 and C.clamp_budget(10 ** 9) == 500000:
        ok("clamp_budget 边界")
    else:
        bad("clamp_budget 边界", (C.clamp_budget(500), C.clamp_budget(10 ** 9)))

    # 记忆裁剪：条数 + 字数两道闸
    hist = [{"src": "x" * 40, "out": "y" * 40} for _ in range(20)]
    got, chars = C.pick_context(hist, 8, 12000)
    if len(got) == 8:
        ok("pick_context 按条数取", "8 条 / %d 字" % chars)
    else:
        bad("pick_context 按条数取", len(got))

    got, chars = C.pick_context(hist, 8, 400)      # 只塞得下 5 条
    if len(got) == 5 and chars <= 400:
        ok("pick_context 按字数裁", "8 条 → %d 条 / %d 字" % (len(got), chars))
    else:
        bad("pick_context 按字数裁", (len(got), chars))

    got, _ = C.pick_context(hist, 0, 12000)
    if got == []:
        ok("pick_context 关掉记忆")
    else:
        bad("pick_context 关掉记忆", got)

    # 文字系统
    kinds = [("你好", "han"), ("hello", "latin"), ("こんにちは", "kana"),
             ("안녕", "hangul"), ("Привет", "cyrillic"), ("สวัสดี", "thai")]
    wrong = [(t, C.script_kind(t)) for t, w in kinds if C.script_kind(t) != w]
    if not wrong:
        ok("script_kind 六种文字")
    else:
        bad("script_kind", wrong)

    # 回复解析：正常 JSON / 带代码围栏 / 完全不是 JSON
    r = C.parse_reply('{"source":"zh","target":"ja","mode":"casual","text":"テスト"}')
    if r["text"] == "テスト" and r["mode"] == "casual":
        ok("parse_reply 标准 JSON")
    else:
        bad("parse_reply 标准 JSON", r)

    r = C.parse_reply('```json\n{"text":"兜底"}\n```')
    if r["text"] == "兜底":
        ok("parse_reply 带代码围栏")
    else:
        bad("parse_reply 带代码围栏", r)

    r = C.parse_reply("这不是 JSON，直接当地文")
    if r["text"] == "这不是 JSON，直接当地文":
        ok("parse_reply 非 JSON 退化")
    else:
        bad("parse_reply 非 JSON 退化", r)

    # 提示词分区
    p = C.build_system_prompt("ja", "casual",
                              [{"src": "我说", "out": "I said", "srcLang": "zh", "tgtLang": "en"}],
                              "埋点 = event tracking",
                              [{"src": "对方说", "out": "they said", "srcLang": "en", "tgtLang": "zh"}])
    checks = [("TARGET: ja" in p, "目标语言"),
              ("埋点 = event tracking" in p, "语境"),
              ("This side's own earlier turns" in p, "本栏记忆区"),
              ("The OTHER side's recent turns" in p, "对方记忆区"),
              ("OVERRIDE: always use the casual" in p, "语气覆盖")]
    miss = [n for c, n in checks if not c]
    if not miss:
        ok("build_system_prompt 分区", "5 个区块")
    else:
        bad("build_system_prompt 分区", miss)

    # 目标语言撞车纠正
    t = C.Translator(config=dict(C.DEFAULT_CONFIG, myLang="zh", peerLang="en"),
                     sessions=[C.new_session("t")])
    if t.resolve_target("toPeer", "这是一句中文") == "en":
        ok("目标语言撞车纠正（中文→说英文）")
    else:
        bad("目标语言撞车纠正", t.resolve_target("toPeer", "这是一句中文"))


# ───────────────────────── 2. 配置自愈 ─────────────────────────

def test_config():
    section("2. 配置自愈（脏值不该把程序搞崩）")

    import translator_core as C

    dirty = {"providers": None, "myLang": "", "peerLang": None,
             "mode": "乱写", "memoryDepth": -7, "contextCharBudget": "abc"}
    t = C.Translator(config=dirty, sessions=[C.new_session("t")])
    c = t.config
    checks = [("providers 变回列表", isinstance(c["providers"], list)),
              ("myLang 补默认", c["myLang"] == "zh"),
              ("peerLang 补默认", c["peerLang"] == "en"),
              ("mode 回落 auto", c["mode"] == "auto"),
              ("memoryDepth 夹到 0", c["memoryDepth"] == 0),
              ("contextCharBudget 补默认", c["contextCharBudget"] == 12000)]
    miss = [n for okk, n in checks if not okk]
    if not miss:
        ok("脏配置自愈", "6 项")
    else:
        bad("脏配置自愈", miss)


# ───────────────────────── 3. 会话与记忆 ─────────────────────────

def test_sessions():
    section("3. 会话与记忆（两栏互不污染）")

    import translator_core as C

    t = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("A")])
    s = t.current_session()
    s["toPeer"] = [{"src": "我说的", "out": "mine"}]
    s["fromPeer"] = [{"src": "对方说的", "out": "theirs"}]

    if len(t.memory("toPeer")) == 1 and t.memory("toPeer")[0]["src"] == "我说的":
        ok("两条记忆线独立")
    else:
        bad("两条记忆线独立", t.memory("toPeer"))

    t.add_session("B")
    if t.active == "B" and t.memory("toPeer") == []:
        ok("新会话记忆为空")
    else:
        bad("新会话记忆为空", (t.active, t.memory("toPeer")))

    t.switch_session("A")
    if len(t.memory("toPeer")) == 1:
        ok("切回会话记忆还在")
    else:
        bad("切回会话记忆还在")

    t.delete_memory("toPeer", [0])
    if t.memory("toPeer") == []:
        ok("删除单条记忆")
    else:
        bad("删除单条记忆")

    if t.add_session("A") is False:
        ok("同名会话拒绝创建")
    else:
        bad("同名会话拒绝创建")

    if t.delete_session("B") and t.active == "A":
        ok("删除会话并自动切换")
    else:
        bad("删除会话并自动切换", t.active)

    one = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("only")])
    if one.delete_session("only") is False:
        ok("最后一个会话不许删")
    else:
        bad("最后一个会话不许删")


# ───────────────────────── 4. 真实 API ─────────────────────────

def test_api():
    section("4. 真实翻译（走 DeepSeek）")

    import translator_core as C

    # 公开项目里不能假设本机有 key —— 没有就跳过，而不是失败。
    # 要真跑这一节：设 PFT_API_KEY（见 README）。
    if not C.read_env_key():
        skip("真实 API 翻译", "没有 %s 环境变量" % C.KEY_ENV_VAR)
        return

    t = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("api")])
    # 第三项容易写错：toPeer 的目标是 peerLang(en)，但输入本身已经是英文，
    # resolve_target() 会翻成中文兜回来 —— 这是有意的防呆，不是 bug。
    cases = [("今天累死了，不想干活了", "toPeer", "en"),
             ("Can you refactor this into a separate module?", "toPeer", "zh"),
             ("そのバグ、明日直しておくね", "fromPeer", "zh")]

    for text, lane, want_tgt in cases:
        try:
            t0 = time.time()
            r = t.translate(text, lane, remember=False)
            dt = time.time() - t0
        except Exception as e:
            bad("翻译 %s" % text[:14], e)
            continue
        if r["text"] and r["target"] == want_tgt:
            ok("翻译 %s" % text[:14], "%.1fs %s→%s %s" %
               (dt, r["source"], r["target"], r["text"][:26]))
        else:
            bad("翻译 %s" % text[:14], r)

    # 记忆确实影响输出（术语一致）
    t2 = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("m")])
    t2.config["peerLang"] = "en"
    try:
        a = t2.translate("采用网关模式", "toPeer", remember=True)
        b = t2.translate("网关那边再确认一下", "toPeer", remember=True)
        if a["text"] and b["text"]:
            ok("带上记忆再翻", b["text"][:40])
        else:
            bad("带上记忆再翻", (a, b))
    except Exception as e:
        bad("带上记忆再翻", e)


# ───────────────────────── 5. 语音识别 ─────────────────────────

def test_asr():
    section("5. 语音识别（SenseVoice，离线）")

    try:
        import asr_worker as W
    except Exception as e:
        bad("导入 asr_worker", e)
        return

    d = W.find_model_dir()
    if not d:
        skip("SenseVoice 模型", "没找到，候选：%s" % W.model_candidates()[0])
        return
    ok("找到模型", os.path.basename(d))

    try:
        b = W.make_backend("sensevoice")
    except Exception as e:
        bad("加载 SenseVoice", e)
        return
    ok("加载 SenseVoice")

    # 模型自带的样例音频，是官方给的，拿来当回归基准
    want = {"zh": "开饭时间", "en": "tribal", "ja": "中学"}
    for lang, key in want.items():
        wav = os.path.join(d, "test_wavs", "%s.wav" % lang)
        if not os.path.isfile(wav):
            skip("识别 %s.wav" % lang, "文件不存在")
            continue
        try:
            t0 = time.time()
            txt = b.transcribe(wav)
            dt = time.time() - t0
        except Exception as e:
            bad("识别 %s.wav" % lang, e)
            continue
        if key in txt:
            ok("识别 %s.wav" % lang, "%.2fs  %s" % (dt, txt[:38]))
        else:
            bad("识别 %s.wav" % lang, "没出现关键词 %r：%s" % (key, txt[:60]))


# ───────────────────────── 6. 数值/绘制 ─────────────────────────

def test_level():
    section("6. 电平映射（必须是 dB，不能线性）")

    import ui_kit as U

    # 实测过的真实麦克风峰值
    want = [(0.001, 0.0, 0.05), (0.01, 0.14, 0.20), (0.022, 0.25, 0.36),
            (0.073, 0.45, 0.60), (0.1, 0.52, 0.66), (0.4, 0.75, 0.90)]
    bads = []
    for peak, lo, hi in want:
        v = U.norm_level(peak)
        if not (lo <= v <= hi):
            bads.append((peak, round(v, 3), lo, hi))
    if not bads:
        ok("norm_level 分布合理", "0.022→%.0f%%  0.073→%.0f%%" %
           (U.norm_level(0.022) * 100, U.norm_level(0.073) * 100))
    else:
        bad("norm_level 分布", bads)

    if U.norm_level(0) == 0 and U.norm_level(1.0) == 1.0 and U.norm_level(None) == 0:
        ok("norm_level 端点")
    else:
        bad("norm_level 端点")

    # 多边形裁剪：蓝色填充是算出来的，不能画成方块
    # ycut 是「保留 y >= ycut 的部分」。
    # 满格 = ycut 0（全留），半格 = 中间，0% = ycut 到底（什么都不留）。
    n_full = len(U.clip_poly_below(U.SPEAKER_SHAPE, 0))
    n_half = len(U.clip_poly_below(U.SPEAKER_SHAPE, U.SPEAKER_H / 2))
    n_none = len(U.clip_poly_below(U.SPEAKER_SHAPE, U.SPEAKER_H))
    if n_full == len(U.SPEAKER_SHAPE) and 3 <= n_half <= len(U.SPEAKER_SHAPE) + 2 and n_none == 0:
        ok("clip_poly_below 裁剪", "满=%d 个点，半=%d 个点，空=%d 个点"
           % (n_full, n_half, n_none))
    else:
        bad("clip_poly_below 裁剪", (n_full, n_half, n_none))

    # 蓝色面积要随音量单调增，否则表针会乱跳
    def area(v):
        part = U.clip_poly_below(U.SPEAKER_SHAPE, U.SPEAKER_H - v * U.SPEAKER_H)
        if len(part) < 3:
            return 0.0
        s = 0.0
        for i in range(len(part)):
            x1, y1 = part[i]
            x2, y2 = part[(i + 1) % len(part)]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    vals = [area(v) for v in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0)]
    if all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)) and vals[0] > 0:
        ok("填充面积随音量单调增", "10%%→%.0f  100%%→%.0f" % (vals[0], vals[-1]))
    else:
        bad("填充面积单调性", [round(v) for v in vals])


# ───────────────────────── 7. 界面冒烟 ─────────────────────────

def test_ui():
    section("7. 界面冒烟（无头，不弹窗）")

    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception as e:
        skip("界面测试", "这台机器开不了 tkinter：%s" % e)
        return

    try:
        import translate_app as UI
    except Exception as e:
        bad("导入 translate_app", e)
        return

    # ★ 前置：没有 key 时 App() 会弹模态向导，测试就会卡死在"等人点"。
    # 只在沙箱里改配置，绝不动真实文件 —— 本项目有过"测试把用户数据清掉"的事故。
    import json as _json
    import translator_core as _C
    if not _C.is_sandboxed():
        bad("界面测试前置检查", "当前不是沙箱路径，拒绝改写配置")
        return
    try:
        with open(_C.CONFIG_FILE, encoding="utf-8") as _f:
            _d = _json.load(_f)
    except Exception:
        _d = dict(_C.DEFAULT_CONFIG)
    _d["setupDone"] = True
    with open(_C.CONFIG_FILE, "w", encoding="utf-8") as _f:
        _json.dump(_d, _f, ensure_ascii=False, indent=2)

    try:
        app = UI.App()
        app.withdraw()
    except Exception as e:
        bad("创建主窗口", e)
        return
    ok("创建主窗口")

    # 构造函数完整性。
    # 这条是被真事逼出来的：有一次往 __init__ 中间插了个 def，
    # 把后半段（状态栏轮询、预热、快捷键、悬浮窗初始化）切进了那个方法里，
    # 结果"本机有 key"时那些代码一行都没跑 —— 程序看起来正常，其实全瘫着。
    need_attrs = ["t", "recorder", "asr", "lane_mine", "lane_peer", "overlay",
                  "hotkeys", "cb_backend", "cb_sess", "_say_queue",
                  "_pump_id", "_warm_id"]
    miss = [a for a in need_attrs if not hasattr(app, a)]
    if not miss:
        ok("App 构造函数跑完整了", "%d 个属性都在" % len(need_attrs))
    else:
        bad("App 构造函数跑完整了", "缺: %s" % miss)

    # "检查更新"的线程必须在 App.__init__ 里启动。
    # 踩过：它被放进了 _run_setup_if_needed()，而那个方法对配好引擎的机器直接 return，
    # 于是老用户的检查从来没跑过 —— 日志里连一行都没有，查了很久。
    import ast as _ast
    _src = open(os.path.join(SRC, "translate_app.py"), encoding="utf-8").read()
    _tree = _ast.parse(_src)
    _in_init = False
    for _node in _ast.walk(_tree):
        if isinstance(_node, _ast.FunctionDef) and _node.name == "__init__":
            for _sub in _ast.walk(_node):
                if isinstance(_sub, _ast.Attribute) and _sub.attr == "_check_updates":
                    _in_init = True
    if _in_init:
        ok("检查更新的线程是在 __init__ 里启动的")
    else:
        bad("检查更新的线程不在 __init__ 里（是不是又放错方法了？）")

    # 快捷键编辑器：键名必须能往返，取当前键位必须和注册用的是同一份来源
    try:
        import overlay as O
        dlg = UI.SettingsDialog(app)
        dlg.withdraw()
        rt = all(O.key_name(0, vk) == name for name, vk in O.HOTKEY_KEYS)
        pair = O.hotkey_pair(app)
        shown = O.key_name(*pair[0])
        if rt and shown in dlg._hk_lbl["toggle"].cget("text"):
            ok("快捷键编辑器", "可选键 %d 个，键名往返一致，显示 %s" % (len(O.HOTKEY_KEYS), shown))
        else:
            bad("快捷键编辑器", "往返=%s 显示=%s 取到=%s" % (rt, dlg._hk_lbl["toggle"].cget("text"), pair))
        dlg.destroy()
    except Exception as e:
        bad("快捷键编辑器", e)

    # 状态栏轮询真的在工作（_pump 是通过 after 排的，能被取消掉就说明排上了）
    try:
        app.after_cancel(app._pump_id)
        ok("状态栏轮询已排上")
    except Exception as e:
        bad("状态栏轮询已排上", e)
    app._pump_id = app.after(120, app._pump)      # 还回去，后面还要用

    # 两栏
    lanes = [("左栏", app.lane_mine), ("右栏", app.lane_peer)]
    want = ["get_input", "set_input", "set_output", "set_pair", "set_busy",
            "set_recording", "set_level", "refresh_memory"]
    for name, lane in lanes:
        miss = [m for m in want if not callable(getattr(lane, m, None))]
        if miss:
            bad("%s 接口" % name, miss)
        else:
            ok("%s 接口完整" % name, "side=%s" % lane.side)

    # 记忆面板：已积累 / 本次带
    sess = app.t.current_session()
    sess["toPeer"] = [{"src": "第%d条" % i, "out": "line %d" % i,
                       "srcLang": "zh", "tgtLang": "en"} for i in range(20)]
    app.t.set_memory(depth=5, budget=12000)
    app.lane_mine.refresh_memory()
    txt = app.lane_mine.lbl_mem.cget("text")
    if "已积累 20 条" in txt and "本次带 5 条" in txt:
        ok("记忆面板区分积累/本次", txt)
    else:
        bad("记忆面板区分积累/本次", txt)

    marked = sum(1 for r in app.lane_mine.tree.get_children()
                 if app.lane_mine.tree.item(r, "values")[2])
    if marked == 5:
        ok("本次会带的那几条打勾", "5 行")
    else:
        bad("本次会带的那几条打勾", marked)

    # 悬浮窗
    try:
        app.toggle_overlay()
        app.update()
        ov = app.overlay
        miss = [m for m in want if not callable(getattr(ov, m, None))]
        if miss:
            bad("悬浮窗 Lane 接口", miss)
        else:
            ok("悬浮窗 Lane 接口完整", "side=%s" % ov.side)
        if ov.attributes("-topmost") and ov.overrideredirect():
            ok("悬浮窗置顶且无边框")
        else:
            bad("悬浮窗置顶且无边框")
        ov.set_side("fromPeer")
        if ov.side == "fromPeer":
            ok("悬浮窗切方向")
        else:
            bad("悬浮窗切方向")
        ov.set_side("toPeer")
        # 会话下拉
        n_items = ov.menu_sess.index("end") + 1
        if n_items >= 4:
            ok("悬浮窗会话下拉", "%d 项" % n_items)
        else:
            bad("悬浮窗会话下拉", n_items)
        # 切会话要同步主窗口
        if "selftest_tmp" not in app.t.session_names():
            app.t.add_session("selftest_tmp")
        app.t.switch_session(app.t.session_names()[0])
        app.load_session_into_ui()
        app.toggle_overlay()
        app.update()
        app.overlay.switch_session([n for n in app.t.session_names()
                                    if n != app.t.active][0])
        app.update()
        if app.cb_sess.get() == app.t.active and app.t.active in app.overlay.btn_sess.cget("text"):
            ok("悬浮窗切会话同步主窗口", app.t.active)
        else:
            bad("悬浮窗切会话同步主窗口", (app.cb_sess.get(), app.t.active))
        app.t.delete_session("selftest_tmp")
    except Exception as e:
        bad("悬浮窗", e)

    # 喇叭、录音状态机
    try:
        L = app.lane_mine
        if L.lvl.winfo_manager():
            bad("闲置时喇叭不该显示")
        else:
            ok("闲置时喇叭隐藏")
        L.set_recording(True)
        if L.lvl.winfo_manager():
            ok("录音时喇叭出现", "按钮=%r" % L.btn_mic.cget("text"))
        else:
            bad("录音时喇叭出现")
        L.set_level(0.6, 1.5, 0.6)
        if "60%" in L.lbl_hint.cget("text"):
            ok("电平百分比显示", L.lbl_hint.cget("text"))
        else:
            bad("电平百分比显示", L.lbl_hint.cget("text"))
        L.set_recording(False)
        if L.lvl.winfo_manager():
            bad("停止后喇叭该收起")
        else:
            ok("停止后喇叭收起")
    except Exception as e:
        bad("录音状态机", e)

    # 单实例守卫
    try:
        if UI.single_instance_guard() is False:
            ok("单实例守卫认出了本窗口")
        else:
            bad("单实例守卫", "没认出自己的窗口")
    except Exception as e:
        bad("单实例守卫", e)

    app.on_close()


# ───────────────────────── 8. 快捷键 ─────────────────────────

def test_hotkeys():
    section("8. 全局快捷键（注册后立刻注销）")

    try:
        import overlay as O
    except Exception as e:
        bad("导入 overlay", e)
        return

    # 用两个没人占的探测键，不要拿生产键去试 ——
    # 程序正开着的时候生产键是被它自己占着的，测了必然"失败"，那是误报。
    probe = {9001: (O.MOD_WIN | O.MOD_ALT, 0x4A, "Win+Alt+J（探测用）"),
             9002: (O.MOD_WIN | O.MOD_ALT, 0x4C, "Win+Alt+L（探测用）")}
    th = O.HotkeyThread(probe)
    th.start()
    time.sleep(1.2)
    if th.registered:
        ok("RegisterHotKey 可用", ", ".join(th.registered.values()))
    else:
        bad("RegisterHotKey 可用", "连探测键都注册不上，环境有问题")
    for hid, v in (th.failed or {}).items():
        print("         %s → %s" % (v[0], v[2]))
    th.stop()

    # 生产键的状态只作参考：程序开着的时候必然是被占用的
    prod = {9003: (O.DEFAULT_TOGGLE[0], O.DEFAULT_TOGGLE[1], O.key_name(*O.DEFAULT_TOGGLE)),
            9004: (O.DEFAULT_CLIP[0], O.DEFAULT_CLIP[1], O.key_name(*O.DEFAULT_CLIP))}
    th2 = O.HotkeyThread(prod)
    th2.start()
    time.sleep(1.2)
    if th2.registered:
        print("  生产键 %s / %s 当前空闲（程序没在跑）"
              % (O.key_name(*O.DEFAULT_TOGGLE), O.key_name(*O.DEFAULT_CLIP)))
    else:
        print("  生产键 %s / %s 当前被占用 —— 如果程序正开着，这是正常的"
              % (O.key_name(*O.DEFAULT_TOGGLE), O.key_name(*O.DEFAULT_CLIP)))
        for hid, v in (th2.failed or {}).items():
            print("         %s → %s" % (v[0], v[2]))
    th2.stop()


# ───────────────────────── 9. 首次运行 / 公版 ─────────────────────────

def test_setup():
    section("9. 首次运行（公开版本不能自带 key）")

    import translator_core as C

    # 9.0 版本比较（纯函数，不联网）。比不出来的一律当"不是新版"。
    cases = [("v1.0.1", "1.0.1", False), ("v1.0.2", "1.0.1", True),
             ("v1.10", "1.9", True), ("v2.0", "v1.99", True),
             ("", "1.0.1", False), ("garbage", "1.0.1", False)]
    wrong = [(a, b, C.parse_version(a) > C.parse_version(b), want)
             for a, b, want in cases
             if (C.parse_version(a) > C.parse_version(b)) != want]
    if not wrong and C.parse_version(C.APP_VERSION) == C.parse_version(C.APP_VERSION):
        ok("版本比较", "APP_VERSION=%s，%d 个用例都对" % (C.APP_VERSION, len(cases)))
    else:
        bad("版本比较", wrong)

    # 9.1 代码里不许出现写死的私有路径。
    # 只看**字符串字面量**——注释里提到"D:\DeepSeekHarness"是在解释为什么不要写死它。
    import ast
    hits = []
    for name in ("translator_core.py", "translate_app.py", "voice_input.py",
                 "asr_worker.py", "overlay.py", "ui_kit.py", "setup_wizard.py"):
        p = os.path.join(SRC, name)
        if not os.path.isfile(p):
            continue
        tree = ast.parse(open(p, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if "DeepSeekHarness" in v or "C:\\Users\\" in v:
                    hits.append("%s:%d %r" % (name, node.lineno, v[:50]))
    if not hits:
        ok("代码里没有写死的本机路径（只看字符串字面量）")
    else:
        bad("代码里有写死的本机路径", hits)

    # 9.2 界面文件里不许出现【已废弃的】快捷键字面量。
    # 踩过：全局键从 Ctrl+Alt+O / Ctrl+Alt+T 换成 Win+Alt+O / Win+Alt+V（旧键被别的程序占用），
    # translate_app.py 里状态栏那行是写死的旧字符串，没跟着改 —— 界面一直显示废弃的键，
    # 而 README 写的是新键，两边对不上。键名只能由 overlay 按 config 生成。
    #
    # 故意写窄：界面里合法地写着 "Ctrl+Enter"，所以不能拿 "Ctrl+" 这种泛模式去扫。
    dead = ("Ctrl+Alt+O", "Ctrl+Alt+T")
    hits2 = []
    for name in ("translate_app.py", "setup_wizard.py", "ui_kit.py"):
        p = os.path.join(SRC, name)
        if not os.path.isfile(p):
            continue
        tree = ast.parse(open(p, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if any(d in v for d in dead):
                    hits2.append("%s:%d %r" % (name, node.lineno, v[:60]))
    if not hits2:
        ok("界面文件里没有废弃的快捷键字面量")
    else:
        bad("界面文件里还写着废弃的快捷键（应由 overlay 生成）", hits2)

    # 9.2 免费机翻后端存在
    t = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("x")])
    keys = [k for _, k in t.backends()]
    if "google" in keys:
        ok("后端列表里有免费机翻")
    else:
        bad("后端列表里有免费机翻", keys)

    # 9.3 可用性探测：干净机器上内置后端必须报不可用
    saved = {}
    for v in ("PFT_API_KEY",):
        saved[v] = os.environ.pop(v, None)
    saved_home = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = os.environ["HOME"] = r"C:\__selftest_none__"
    try:
        t2 = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("x")])
        k, why = t2.backend_available("builtin")
        if not k and why:
            ok("干净机器上内置后端标记为不可用", why[:40])
        else:
            bad("干净机器上内置后端标记为不可用", (k, why))

        # 它也不该出现在列表里 —— 否则就是"列得出来、选了什么也不能用"的死选项。
        listed = [k for _, k in t2.backends()]
        if "builtin" not in listed:
            ok("干净机器上不列出内置 DeepSeek", "、".join(listed))
        else:
            bad("干净机器上不该列出内置 DeepSeek", listed)

        if t2.has_own_backend() is False and t2.needs_setup() is True:
            ok("干净机器会弹首次运行向导")
        else:
            bad("干净机器会弹首次运行向导",
                (t2.has_own_backend(), t2.needs_setup()))

        k2, _ = t2.backend_available("google")
        if k2:
            ok("免费机翻始终标记为可用")
        else:
            bad("免费机翻始终标记为可用")

        if t2.config.get("setupDone") is False:
            ok("默认 setupDone = False")
        else:
            bad("默认 setupDone")
    finally:
        for v, val in saved.items():
            if val is not None:
                os.environ[v] = val
        if saved_home:
            os.environ["USERPROFILE"] = saved_home

    # 9.4 本机有 key 时不该弹（用当前真实环境）
    t3 = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("x")])
    if t3.needs_setup() == (not t3.has_own_backend()):
        ok("needs_setup 与 has_own_backend 一致",
           "有 key" if t3.has_own_backend() else "没 key")
    else:
        bad("needs_setup 与 has_own_backend 一致")

    if C.Translator(config=dict(C.DEFAULT_CONFIG, setupDone=True),
                    sessions=[C.new_session("x")]).needs_setup() is False:
        ok("setupDone=True 之后不再问")
    else:
        bad("setupDone=True 之后不再问")

    # 9.5 向导能建出来，且空 key 会被拦住
    try:
        import tkinter as tk
        from tkinter import ttk
        import setup_wizard as W
        root = tk.Tk()
        root.geometry("600x400+100+100")
        root.update()          # 主窗口必须先映射，否则向导作为 transient 不会显示
        root.t = C.Translator(config=dict(C.DEFAULT_CONFIG), sessions=[C.new_session("x")])
        w = W.SetupWizard(root)
        w.update()
        if w.title():
            ok("向导能创建", w.title())
        if w.winfo_ismapped():
            ok("向导真的显示出来了", "%dx%d" % (w.winfo_width(), w.winfo_height()))
        else:
            bad("向导真的显示出来了", "父窗口没映射时子窗口不会显示")
        if str(w.cb_preset.cget("state")) == "disabled":
            ok("默认选免费机翻时 key 那栏是灰的")
        else:
            bad("默认选免费机翻时 key 那栏是灰的", w.cb_preset.cget("state"))
        w.v_choice.set("key")
        w._sync()
        w.update()
        if str(w.cb_preset.cget("state")) == "readonly":
            ok("切到 key 后下拉解锁且是 readonly")
        else:
            bad("切到 key 后下拉解锁且是 readonly", w.cb_preset.cget("state"))
        w.v_key.set("")
        w.on_ok()
        w.update()
        if w.winfo_exists():
            ok("空 key 被拦住", w.lbl_msg.cget("text"))
        else:
            bad("空 key 被拦住", "竟然放行了")
        w.v_choice.set("google")
        w.on_ok()
        if w.result is True and root.t.config.get("activeBackend") == "google":
            ok("选免费机翻后写入 activeBackend=google")
        else:
            bad("选免费机翻后写入", (w.result, root.t.config.get("activeBackend")))
        if root.t.config.get("setupDone") is True:
            ok("选完之后 setupDone=True")
        else:
            bad("选完之后 setupDone=True")
        root.destroy()
    except Exception as e:
        bad("向导测试", e)


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="跳过联网 / 模型 / 界面部分")
    ap.add_argument("--no-ui", action="store_true", help="跳过界面部分")
    a = ap.parse_args()

    print()
    print("源目录:", SRC)

    # ⚠️ 必须在任何测试之前进沙箱。
    # Translator() 的 save_config/save_sessions 默认写真实文件，
    # 测试里随手 new 再保存就会覆盖用户的会话和设置（真发生过）。
    import translator_core as _C
    cfg_p, sess_p = _C.use_sandbox_config()
    print("沙箱:", os.path.dirname(cfg_p))
    if not _C.is_sandboxed():
        print("!! 沙箱没生效，拒绝运行，以免覆盖真实数据")
        return 2

    test_pure()
    test_config()
    test_sessions()
    test_level()

    if a.offline:
        skip("真实 API 翻译", "--offline")
        skip("语音识别", "--offline")
        skip("界面冒烟", "--offline")
        test_setup()
        skip("全局快捷键", "--offline")
    else:
        test_api()
        test_asr()
        if not a.no_ui:
            test_ui()
        test_setup()
        test_hotkeys()

    print()
    print("=" * 68)
    print("  通过 %d   失败 %d   跳过 %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print()
        print("  失败项:")
        for n, why in FAIL:
            print("    - %s  %s" % (n, why))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
