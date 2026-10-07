# 后端接口 · translator_core.py

给要重写前端的人（或 AI）看的。**只需要读这一份，不用读 translate_app.py。**

---

## 一句话

`translator_core.py` 是全部逻辑，**不导入 tkinter**。
`translate_app.py` 是现在的 tkinter 前端，**随时可以整个删掉重写**。

前端只做三件事：收集输入、调 `Translator`、显示结果。
**不要**在前端里拼提示词、发 HTTP、读写 json 文件、算语言、裁剪记忆 —— 那些都在核心里。

文件位置：

```
src/translator_core.py        后端（无界面依赖）
src/translate_app.py          现在的 tkinter 前端（可替换）

运行时的配置和会话【不在源码目录里】，在用户数据目录：
    %APPDATA%\pretend-foreigner\pretend_foreigner.config.json     配置（后端读写，前端不要碰）
    %APPDATA%\pretend-foreigner\pretend_foreigner.sessions.json   会话与记忆（同上）

`use_user_data_dir()` 负责把这两个路径指过去（由 `main()` 调用）；
测试里用 `use_sandbox_config()` 指到临时目录 —— 那个会删文件，只在测试里用。
```

---

## 快速上手

```python
from translator_core import Translator, lang_name, ApiError

t = Translator()                      # 自动读配置和会话文件

# 用户点「翻译」时，在工作线程里调：
r = t.translate("这个 bug 我明天修一下", lane="toPeer")
r["text"]                             # "このバグ、明日直しとくね"
```

`lane` 只有两个值：

| lane | 含义 | 译成什么语言 |
|---|---|---|
| `"toPeer"` | 我说的话 | `config["peerLang"]` |
| `"fromPeer"` | 对方说的话 | `config["myLang"]` |

### 两条记忆线为什么要互相可见（但只准解指代）

分两条线的原因：对方那一大段英文不该把你的短中文带成翻译腔。

但**指代关系是跨栏的**。你说「行，那就先这样」，这个「这样」指的是对方刚说的话，
不在你自己那栏里。所以每一栏翻译时会额外带上对方最近几条，并且在提示词里
**明确分区块、明确规定用途**：

```
The OTHER side's recent turns - this is what the current side is replying to.
Use these ONLY to understand the referent: what "it" / "that" / "the above"
means, and what a short reply like "yes" / "ok" / "no" / "对" / "行" / "好"
is agreeing or disagreeing with. Quote nothing from them.
Do NOT copy their wording, and do NOT let their register change this side's
register.

This side's own earlier turns (most recent last):
Use these for terminology and tone consistency.
```

条数由 `config["crossMemoryDepth"]` 控制，**0 = 关掉**。
风格永远只由本栏决定，对方那份只贡献指代。

> ⚠️ **实测说明**：这个机制在合成用例里**没能测出明显差别**。
> 用中→英/日/法/俄/德试过裸回复（「别」「别删」「那个先不用了」）和承上启下句，
> 开不开的结果基本一样 —— 因为模型本来就习惯把省略的东西保持含糊
> （"Don't" / "Pas besoin de ça"），这在目标语言里通常也对。
> 它属于**防御性设计**：多给一份指代信息，成本约 2 条，消除"抓错指代对象"这一类失败。
> 如果你在实际使用中碰到翻错的例子，那才是它真正生效的场景。

---

## 线程规则（重要）

**`translate()` 是阻塞的，0.5–3 秒。** 界面必须自己开线程调，否则主循环会卡死。

```python
import threading

def worker():
    try:
        r = t.translate(text, lane)
    except ApiError as e:
        root.after(0, lambda: show_error(str(e)))     # 回主线程再碰控件
    else:
        root.after(0, lambda: show_result(r))

threading.Thread(target=worker, daemon=True).start()
```

**所有 UI 更新都必须回到主线程。** 核心里的方法本身不碰界面，从哪个线程调都安全；
但 `Translator` 内部会写 json 文件，同一时刻只调一次 `translate()` 就行。

---

## Translator 的方法

### 翻译

```python
t.plan(text, lane, mode=None, remember=True) -> dict
t.translate(text, lane, mode=None, remember=True) -> dict
```

- `plan()` **不发请求**，只算出这次要用的提示词和统计。用来在状态栏先显示「翻译中…」。
- `mode`：`"auto"` / `"precise"` / `"casual"`，不传就用 `config["mode"]`。
- `remember=True` 时会把这一条追加进本栏记忆并落盘。做「试翻一下不记录」时传 `False`。

**`translate()` 返回**：

```python
{
  "text":         "このバグ、明日直しとくね",   # 译文
  "source":       "zh",        # 判定出的源语言
  "target":       "ja",        # 实际用的目标语言（可能被脚本纠正过）
  "mode":         "casual",    # 判定出的语域
  "backend":      "builtin",   # 用了哪个后端
  "lane":         "toPeer",
  "elapsed":      1.13,        # 秒
  "ctx_count":    3,           # 本栏带了几条
  "ctx_chars":    412,
  "cross_count":  1,           # 参照了对方几条
  "cross_chars":  64,
  "memory_count": 9,           # 本栏翻完之后总条数
}
```

**`plan()` 返回**：

```python
{
  "backend": "builtin", "lane": "toPeer", "target": "ja", "mode": "casual",
  "system_prompt": "...",      # 完整提示词，想调试就看这个
  "context": [...],            # 本栏实际带上的条目
  "cross_context": [...],      # 对方那几条
  "ctx_count": 3, "ctx_chars": 412,
  "cross_count": 1, "cross_chars": 64,
  "depth": 8, "cross_depth": 2, "budget": 12000,
  "remember": True,
}
```

**失败一律抛 `ApiError`**，`str(e)` 可以直接显示给用户。可能的消息：
`没填 Base URL` / `没提供 API Key（设 PFT_API_KEY 环境变量，或改用别的引擎）` /
`HTTP 401：...` / `连不上：...` /
`Codex 额度已用完` / `Claude 未登录（需要 Pro）` / `lane 只能是 toPeer 或 fromPeer`

### 配置

```python
t.config                      # dict，可直接读
t.save_config() -> bool
t.save_sessions() -> bool
t.save_all() -> bool

t.set_langs("zh", "en")       # 我的语言 / 对方语言
t.set_mode("casual")          # auto | precise | casual
t.set_memory(depth=8, budget=12000, cross=2)   # 条数 0-200，字数 1000-500000，参照 0-20
t.set_backend("builtin")
t.active_backend() -> "builtin"
```

`t.config` 的字段：

```python
{
  "providers": [ {...} ],       # 自定义服务，见下
  "activeBackend": "builtin",   # builtin | provider:<名字> | codex | claude
  "myLang": "zh",               # ISO 639-1
  "peerLang": "en",
  "mode": "auto",               # auto | precise | casual
  "memoryDepth": 8,             # 本栏记忆 0-200 条
  "contextCharBudget": 12000,   # 1000-500000 字
  "crossMemoryDepth": 2,        # 允许参照对方最近几条，0 = 关
  # 下面两个前端自己塞的，核心不管：
  "windowGeometry": "1240x860",
  "paneSash": 610,
}
```

### 后端列表

```python
t.backends() -> [("内置 DeepSeek (DSH key)", "builtin"),
                 ("自定义 · 我的服务 (gpt-4o)", "provider:我的服务"),
                 ("codex (luna·需额度)", "codex"),
                 ("claude (需 Pro)", "claude")]
```

返回 `[(显示名, key)]`。下拉框显示第一项，选中后把 key 传给 `set_backend()`。

### 会话

```python
t.session_names() -> ["会话 1", "重构任务"]
t.active -> "会话 1"                    # 当前会话名（可直接赋值，但建议用 switch_session）
t.current_session() -> dict             # 当前会话的完整数据
t.switch_session(name) -> bool
t.add_session(name) -> bool             # 重名返回 False
t.rename_session(old, new) -> bool
t.delete_session(name) -> bool          # 只剩一个时返回 False，不让删
t.note() -> str                         # 本会话的语境/术语
t.set_note(text)
```

会话结构：

```python
{
  "name": "会话 1",
  "note": "埋点 = event tracking",       # 语境/术语，每次请求都带上
  "toPeer":   [ {记忆条目}, ... ],        # 我说的那条线
  "fromPeer": [ {记忆条目}, ... ],        # 对方说的那条线
}
```

### 记忆

```python
t.memory(lane) -> [ {记忆条目}, ... ]    # 返回副本，
t.delete_memory(lane, [2, 5])            # 按下标删，内部会倒序处理
t.clear_memory(lane)
```

记忆条目：

```python
{"src": "这个 bug 我明天修一下", "out": "このバグ、明日直しとくね",
 "srcLang": "zh", "tgtLang": "ja"}
```

### 服务商（设置界面用）

```python
t.get_provider(name) -> dict | None
t.upsert_provider({"name":..., "baseUrl":..., "apiKey":..., "model":..., "useProxy": False})
t.delete_provider(name)
t.probe_models(base, key, use_proxy=False) -> ["deepseek-flash", "deepseek-v4-pro"]
t.probe_chat(base, key, model, use_proxy=False) -> {和 translate() 同结构}
```

`probe_*` 也是阻塞的，设置窗口里调要 `update_idletasks()` 或开线程。
`useProxy=True` 走 `127.0.0.1:7890`；默认 `trust_env=False`，
**不会**被系统里的 `HTTPS_PROXY` 影响。

---

## 辅助函数（前端可以直接用）

```python
LANGS              # [(code, 显示名), ...] 19 种语言
LANG_LABEL         # {"zh": "中文（简体）", ...}
CODE_OF_LABEL      # {"中文（简体）": "zh", ...}
MODE_CODES         # ["auto", "precise", "casual"]
lang_name("ja")    # "日本語"，查不到就原样返回

MEM_MIN, MEM_MAX             # 0, 200
BUDGET_MIN, BUDGET_MAX, BUDGET_STEP   # 1000, 500000, 1000

clamp_depth(v, default=8)        # 夹到 0-200，脏值回落默认
clamp_budget(v, default=12000)   # 夹到 1000-500000
```

⚠️ **语言下拉框必须用 `LANGS`**，不要自己硬编码一份。加语言只改核心这一处。

---

## 前端不该做的事

| 别做 | 为什么 |
|---|---|
| 自己拼提示词 | 提示词是核心资产，改一处生效一处 |
| 直接 `requests.post` | 代理、重试、404 回退、错误翻译都在 `call_chat` 里 |
| 直接读写那两个 json | 并发写会互相覆盖；`Translator` 内部有夹取和兼容逻辑 |
| 自己判断语言 | `script_kind()` + `resolve_target()` 已经处理了目标语言撞车 |
| 自己裁剪记忆 | `pick_context()` 同时按条数和字数裁 |
| 显示 `t.config["providers"][i]["apiKey"]` 明文 | 除非用户点了「显示」 |

---

## 最小前端骨架

丢掉 `translate_app.py` 后，一个新前端最少只要这些：

```python
import threading
import tkinter as tk
from translator_core import Translator, ApiError, lang_name

t = Translator()
root = tk.Tk()

inp = tk.Text(root, height=6); inp.pack(fill="x")
out = tk.Text(root, height=6); out.pack(fill="x")
status = tk.Label(root); status.pack()

def go(lane):
    text = inp.get("1.0", "end").strip()
    if not text:
        return
    status.config(text="翻译中…")
    def work():
        try:
            r = t.translate(text, lane)
        except ApiError as e:
            root.after(0, lambda: status.config(text="失败：" + str(e)))
        else:
            root.after(0, lambda: (out.delete("1.0", "end"),
                                   out.insert("1.0", r["text"]),
                                   status.config(text="%s→%s / %s / %.1fs" % (
                                       lang_name(r["source"]), lang_name(r["target"]),
                                       r["mode"], r["elapsed"]))))
    threading.Thread(target=work, daemon=True).start()

tk.Button(root, text="我 → 对方", command=lambda: go("toPeer")).pack()
tk.Button(root, text="对方 → 我", command=lambda: go("fromPeer")).pack()
root.mainloop()
```

双栏 + 会话 + 记忆列表都可以照这个往上加，核心一行都不用动。

---

## 自检命令

```bash
# 后端自跑三个用例，不开界面，不需要 tkinter
python src/translator_core.py
```

输出：

```
后端: ['内置 DeepSeek (DSH key)', 'codex (luna·需额度)', 'claude (需 Pro)']
会话: ['会话 1']  当前: 会话 1
语言: 我=zh 对方=ja
记忆: 7 条 / 12000 字

  [toPeer] 今天累死了，不想干活了
      目标=ja 后端=builtin 记忆=1条/25字
      -> 今日マジ疲れた、もう働きたくない  (1.1s, zh/casual)
```

改完前端先跑这个：它不碰界面，能立刻区分是后端坏了还是前端坏了。

---

# 语音输入 · voice_input.py

跟翻译核心**互相独立**。不想要语音的前端可以完全不 import 这个文件。

## 为什么是独立进程

`asr_worker.py` 是一个常驻子进程，不是同进程加载。三个原因：

1. **OpenMP 冲突。** torch / ctranslate2 / sherpa-onnx 各带一份 `libiomp5md.dll`，
   同进程加载直接崩：`OMP: Error #15 ... already initialized`（本机实测）。
   分开跑，各自干净。
2. **模型常驻。** SenseVoice 加载要 2.3 秒，加载一次之后每句只要 0.25–0.5 秒。
3. **崩了不带崩界面。**

## 用法

```python
from voice_input import Recorder, AsrClient, list_input_devices, default_input_device

# 录音（16kHz 单声道，ASR 最喜欢的格式）
rec = Recorder(device=None)          # None = 系统默认麦克风
rec.start()
...                                  # 用户说话；期间可以读 rec.level() 画电平条
wav = rec.stop()                     # 返回 wav 路径；没录到东西返回 None
# rec.cancel()                       # 丢弃

# 识别（阻塞，界面要开线程；首次要等模型加载）
asr = AsrClient(backend="sensevoice")
asr.warm_up()                        # 后台预热，可选
text = asr.transcribe(wav)
asr.stop()                           # 退出子进程

# 设备
list_input_devices()                 # [(编号, 名称, 声道数, 默认采样率)]
default_input_device()               # 编号
```

## 后端选择

| backend | 模型 | 中文 CER | 加载 | 每句 | 说明 |
|---|---|---|---|---|---|
| `sensevoice` | SenseVoiceSmall int8（239 MB） | **5.9%** | 2.3s | 0.3s | 首选。中文准得多，输出**简体**带标点 |
| `whisper` | faster-whisper base | 24.8% | 6.9s | 0.5s | 兜底。多语言稳，但中文同音字错得多，还会输出繁体 |

同一批音频实测（Windows TTS 合成，人工核对）：

```
参考              我想问一下，我在滨海新区有房，所以我必须拿到抚养权
SenseVoice       我想问一下，我在滨海新区有房，所以我必须拿到抚养权。     CER 0.0%
whisper base     我想问一下,我在宾海新区有房,所以我必须拿到福洋权。       CER 13.0%

参考              把配置文件里的超时改成三百，然后重启一下服务，顺便看看日志
SenseVoice       把配置文件里的超时改成300，然后重启一下服务，顺便看看日志。  CER 11.1%*
whisper base     把配置文件里的超时改成300然后重启一下服务 顺便看看日质      CER 14.8%

参考              这个接口的响应时间太慢了，帮我加个缓存层，五分鐘的过期时间就够了
SenseVoice       这个接口的响应时间太慢了，帮我加个缓存层，5分钟的过期时间就够了。 CER 6.7%*
whisper base     這個接口的響應時間太慢了幫我加個緩存層五分鐘的過期時間就夠了   CER 46.7%
```

`*` 那两条不是错，是 SenseVoice 做了 **ITN 数字规整**（三百 → 300、五分鐘 → 5分钟）。
对翻译输入来说这是好事。

模型放在 `models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/`。
下载地址（155 MB）：

```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
```

## 配置字段

```python
"asrBackend": "sensevoice",   # sensevoice | whisper
"asrDevice": None,            # 麦克风编号，None = 系统默认
"asrWarmup": True,            # 启动 3 秒后在后台预加载模型
```

## 踩过的坑

- **sherpa-onnx 1.13 的 API 变了**：没有 `stream.accept_wave_file()`，
  也没有 `sherpa_onnx.read_wave()`。要自己用 `wave` 模块读 wav，
  转成 float32 归一化数组，再 `stream.accept_waveform(采样率, 数组)`。
  采样率不一致时 sherpa 内部会重采样（会往 stderr 打一行 resampler 日志，无害）。
- **`from_sense_voice()` 没有 `hotwords_file` / `hotwords_score` 参数**（那是 paraformer 的），
  传了会 TypeError。
- **torch 要 `KMP_DUPLICATE_LIB_OK=TRUE` 才能导入**（本机 torch 2.11.0+cu128）。
  走 sherpa-onnx 就用不着 torch，所以不要为了 ASR 去动它。
- 子进程要加 `CREATE_NO_WINDOW`（`creationflags=0x08000000`），否则从 pythonw 启动会弹黑框。

---

# 悬浮窗 · overlay.py

主窗口 1240×860，和浏览器并排太占地方。悬浮窗是**第二个 Lane**：
它实现了和主窗口 `Lane` 完全一样的一组方法，所以 `translate_lane()` 和整套录音流程
可以直接拿来用，不用复制逻辑。

```python
# 悬浮窗必须具备的接口（主窗口的流程只调这些）
side                                   # "toPeer" / "fromPeer"（属性，不是方法）
get_input() / set_input(t)
set_output(t) / set_pair(t)
set_busy(bool)
set_recording(on, elapsed) / set_level(v, elapsed, raw)
refresh_memory()
```

## 布局

```
假装外国人 · 19 条        chatGPT   ⤢ ◐ ×     ← 拖这里移动；⤢ 开主窗口，◐ 透明度，× 隐藏
[我 → 对方] [对方 → 我]              剪贴板
┌────────────────────────────────┐
│ 输入                            │
└────────────────────────────────┘
[翻译] [🎤 说话] [喇叭] [复制]   1.2s 电平 62%
┌────────────────────────────────┐
│ 译文                            │
└────────────────────────────────┘
```

- `overrideredirect(True)` —— 去掉标题栏才像浮层
- `attributes("-topmost", True)` —— 置顶
- 标题栏拖动；松手时离边缘 24px 内**自动吸边**
- `◐` 循环 100% / 92% / 85% / 75% 透明度
- 位置、透明度、上次用的方向都存进 config

## 全局快捷键

| 键 | 作用 |
|---|---|
| **Win+Alt+O** | 显示 / 隐藏悬浮窗 |
| **Win+Alt+V** | 把剪贴板内容翻译掉（会先自动开悬浮窗） |

**为什么是 Win+Alt 而不是更好记的组合** —— 实测结果：

```
Ctrl+Alt+O    已被占用（错误码 1409）
Ctrl+Alt+T    已被占用
Ctrl+Shift+O  空着，但 Chrome 用它开书签管理器  ← 全局注册会从所有程序里抢走
Ctrl+Shift+T  空着，但浏览器用它「重开刚关掉的标签页」
Alt+Shift+*   系统切换输入法，绝对不能碰
Win+Alt+O/V   空着，且系统只占了 R / G / PrtScn / B / Enter
```

**全局快捷键是独占的**：注册了就会在**所有程序**里拦截这个组合。
所以不能用浏览器 / 编辑器的常用键，哪怕它们当前没人占。

键位存在 `config["hotkeyToggle"]` / `["hotkeyClipboard"]`，格式 `[修饰键, 虚拟键码]`：

```python
MOD_ALT=0x0001  MOD_CONTROL=0x0002  MOD_SHIFT=0x0004  MOD_WIN=0x0008
```

## 实现要点

- **快捷键必须单开线程。** `RegisterHotKey(hwnd=None)` 把 `WM_HOTKEY` 投递到
  **注册它的那个线程**的消息队列；主线程被 tkinter 占着，从里面 `PeekMessage`
  会把 tk 自己的消息也捞走。所以用一个专用线程跑 `GetMessageW` 循环，
  命中后往 `queue` 丢一个 id，主线程 `after(120)` 轮询取走
  （跨线程直接碰 tkinter 控件不安全）。
- **取错误码要用 `ctypes.WinDLL(..., use_last_error=True)` + `ctypes.get_last_error()`。**
  默认的 `ctypes.windll` 不捕获 last error，取到的是脏值（在别处栽过一次）。
- `overrideredirect` 窗口不在任务栏、不进 Alt+Tab —— 这正是浮层想要的，
  但要自己提供关闭按钮（标题栏那个 `×`，点了是 `withdraw()`）。
- 关窗时记得 `hotkeys.stop()` 和 `UnregisterHotKey`，否则退出后快捷键还被占着。
