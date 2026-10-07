# 假装外国人翻译器 · Pretend Foreigner Translator

跟 Claude / GPT 聊天时用的**双向翻译工具**。

你说中文，它译成自然地道的英文发过去；对方回英文，它译成中文给你看。
**两条记忆线分开** —— 你的口语不会被对方的书面语带跑，对方的正式腔也不会被你的"哈哈"污染。

```
我 → 对方   中文（简体）→ English      casual     ← 你说的话，记你自己的用词
对方 → 我   English → 中文（简体）      precise    ← 对方的话，记对方的术语
```

---

## 下载与安装

**Windows 专用。** 两种装法，功能完全一样：

> **下载页：https://github.com/NeoHotaru/pretend-foreigner-translator/releases**

| 包 | 大小 | 说明 |
|---|---|---|
| **安装包** `pretend-foreigner-setup-1.0.0.exe` | 200 MB | 双击安装。向导里可以改安装目录（默认在当前用户的 `%LOCALAPPDATA%\Programs`，**那一页会显示各盘剩余空间**，C 盘紧就当场改）。带开始菜单、桌面快捷方式、卸载器。 |
| **便携版** `pretend-foreigner-portable-1.0.0.zip` | 234 MB | 解压到任意位置，双击里面的 `pretend-foreigner.exe`。不写注册表、不装服务。 |

两个包**都已经内含 228 MB 的语音识别模型**，装完就能用语音。
（只有从源码运行才需要自己下模型，见下面的「依赖」。）

> **首次运行会被 Windows 拦一下。** 程序没有代码签名证书，SmartScreen 会显示
> "未知发布者"。点【更多信息】→【仍要运行】即可。个别杀软可能直接隔离文件，
> 那就先把它加进白名单再运行。

**配置和会话不会写在程序目录里** —— 它们在 `%APPDATA%\pretend-foreigner\`。
所以装到哪个盘、以后怎么更新，你的设置和会话都不会丢。

---

## 它解决什么问题

直接拿翻译软件跟 AI 聊天有两个毛病：

1. **翻译腔。** 一句"今天累死了，不想干活了"译成
   "Today I am extremely tired and do not wish to work" —— 对方一眼看出你不在说人话。
   这个工具会判语气：闲聊就译成 "ugh today totally wiped me"，任务就译成规整的英文。
2. **记忆串味。** 对方写了一大段正式的技术评价，你回一句"行，那就这样"——
   如果共用一份上下文，那份英文会把你这句短中文也拉成书面语。

所以分了两条线，各自只记自己那一侧的原文和译文。
（但每栏翻译时会**额外看对方最近几条**，只为了搞清"那个""这样"指的是什么。）

---

## 快速开始

```bash
python src/translate_app.py            # 有控制台，方便看报错
wscript run/启动假装外国人.vbs          # 平时用这个，无控制台
```

第一次打开会让你选一个翻译引擎：

- **免费机翻** —— 不用注册、不用填 key，装完就能用。
  代价是没有语气判定、不记上下文、一句话一句话直译；国内需要能访问 Google。
- **用你自己的 API Key** —— 质量明显更好。
  推荐 DeepSeek（国内直连，大约 ¥1 / 百万字），向导里有直达链接。

选完之后可以在「设置」里随时改。

> ⚠️ **向导里那一片是灰的，不是坏了。** 默认选中「免费机翻」时，下面的
> 「服务商 / Base URL / API Key / 模型」以及「读取模型 / 测试连通 / 去哪里拿 Key」
> 都【故意】不可点 —— 免费机翻用不到它们。
> 点上方的第二项「用我自己的 API Key」，它们立刻就会亮。

### 依赖

```
Python 3.10+  ✓ tkinter  ✓ requests  ✓ numpy  ✓ scipy
sounddevice                  ← 语音输入（可选）
sherpa-onnx + onnxruntime    ← 语音识别（可选，纯 CPU 就够）
```

```bash
pip install requests numpy scipy sounddevice sherpa-onnx onnxruntime
```

**语音识别是可选的。** 不装 sherpa-onnx 的话，翻译和悬浮窗照常用，只是「🎤 说话」会报错。

语音模型（228 MB）**不在 git 仓库里**（`.gitignore` 排除了它），要单独下。
从源码运行就得自己下；上面那两个发行包已经内含，不用管这一段：

```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
```

解压到 `models/` 下面即可。也可以放别处，用环境变量指过去：

```bash
set PFT_MODEL_DIR=D:\somewhere\sherpa-onnx-sense-voice-...
```

---

## 界面

**主窗口**（两栏并排，可拖分栏线）

```
会话 [chatGPT ▾] [新建][重命名][删除] │ 后端 [内置 DeepSeek ▾][设置][悬浮窗] │ 语气 [自动判断 ▾]
我的语言 [中文（简体）▾]  对方语言 [English ▾]  记忆 [8]条 / [12]千字 / 参照对方 [2]条  语境/术语 [___]

┌─ 我 → 对方  中文→English ─────┐  ┌─ 对方 → 我  English→中文 ─────┐
│ 输入                          │  │ 输入                          │
│ [翻译] [🎤 说话] [喇叭] [复制译文] [清空]              Ctrl+Enter │
│ 译文                          │  │ 译文                          │
│ 本栏记忆  已积累 19 条 · 本次带 7 条 / 612 字                   │
│  │ 原文            │ 译文            │ 本次 │                    │
│ [删掉选中] [清空本栏] [复制选中原文]                            │
└───────────────────────────────┘  └───────────────────────────────┘
```

**悬浮窗**（`Win+Alt+O` 开合）—— 跟浏览器并排时用这个

```
假装外国人 · 19 条        chatGPT ▾   ⤢ ◐ ×
[我 → 对方] [对方 → 我]              剪贴板
┌──────────────────────────────┐
│ 输入                          │
└──────────────────────────────┘
[翻译] [🎤 说话] [喇叭] [复制]   1.2s 电平 62%
┌──────────────────────────────┐
│ 译文                          │
└──────────────────────────────┘
```

### 快捷键

| 键 | 作用 |
|---|---|
| `Win+Alt+O` | 显示 / 隐藏悬浮窗（全局，其它程序里也能按） |
| `Win+Alt+V` | 翻译剪贴板内容 |
| `Ctrl+Enter` | 在某一栏里翻译 |
| `Esc` | 取消正在录的音 |

---

## 用到的技术

| | |
|---|---|
| 翻译 | DeepSeek / 任何 OpenAI 兼容接口 / Google 免费端点 |
| 语音识别 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) + [SenseVoiceSmall](https://github.com/QwenAudio/SenseVoice)（中文 CER 7.81%，比 Whisper 好约 3 倍） |
| 界面 | tkinter |
| 音频 | sounddevice |

**中文识别为什么不用 Whisper**：同一批音频实测，SenseVoice 平均 CER 5.9%，
faster-whisper base 24.8%，而且 Whisper 会把"日志"听成"日质"、还会输出繁体。
详见 `项目书.md` §5.5。

---

## 目录

```
src/translator_core.py   后端核心（不 import tkinter）
src/translate_app.py     主窗口
src/overlay.py           悬浮窗 + 全局快捷键
src/voice_input.py       录音 + 识别子进程客户端
src/asr_worker.py        ASR 子进程
src/ui_kit.py            共用绘制零件
src/setup_wizard.py      首次运行向导
docs/CORE_API.md         后端接口文档（想换前端读这个）
selftest.py              一条命令跑完 63 项回归
项目书.md                 完整设计与踩坑记录
```

---

## 自检

```bash
python selftest.py             # 全部 63 项，约 20 秒
python selftest.py --offline   # 跳过联网/模型/界面，约 1 秒
```

改完代码先跑这个，它不依赖具体界面实现，能立刻分清是后端坏了还是前端坏了。

---

## 隐私

- **不带任何预置 API Key。** 首次运行必须自己选引擎。
- 翻译请求直接发给你选定的服务商（或 Google 免费端点），本项目不经过任何中间服务器。
- **语音识别在本机跑**，音频不出机器。
- 配置和会话存在 `%APPDATA%\pretend-foreigner\`（`pretend_foreigner.config.json` /
  `.sessions.json`），**不在程序目录里** —— 装到哪、怎么更新，设置都不丢。
  前者含明文 API Key，别提交到 git（`.gitignore` 已排除）。
- 程序**不会去翻别处的凭据**。它只认一个属于本项目自己的环境变量 `PFT_API_KEY`；
  不设它就走首次运行向导，和你自己机器上的行为一样。
