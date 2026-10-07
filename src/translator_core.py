# -*- coding: utf-8 -*-
"""
translator_core.py  —  假装外国人翻译器的后端

这个文件不导入 tkinter，不碰任何界面。所有逻辑都在这里，
前端（QT / Web / tkinter / 命令行）只通过 Translator 这一个类调用。

    from translator_core import Translator
    t = Translator()
    r = t.translate("这个 bug 我明天修一下", lane="toPeer")
    r["text"]        -> "このバグ、明日直しとくね"
    r["source"]      -> "zh"
    r["target"]      -> "ja"
    r["mode"]        -> "casual"

约定：
    · translate() 是**阻塞**的，大约 0.5-3 秒。界面请自己开线程调，别卡主循环。
    · 所有返回值都是普通 dict / list / str，没有自定义对象，方便序列化。
    · 语言用 ISO 639-1 代码（"zh" / "en" / "ja" …），"auto" 表示中英互转。
    · 两条记忆线 key 是 "toPeer"（我说的）和 "fromPeer"（对方说的）。
"""

import ctypes
import json
import os
import re
import shutil
import time
from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None

APP_NAME = "假装外国人翻译器"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "pretend_foreigner.config.json")
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pretend_foreigner.sessions.json")
LEGACY_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "translate_app.config.json")
LEGACY_SESSION = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "translate_app.sessions.json")
LOG_FILE = os.path.join(os.environ.get("TEMP", os.path.dirname(os.path.abspath(__file__))),
                        "translate_app.log")

# 内置 DeepSeek 的 key 只认【本项目自己的】这个环境变量。
# 不读别的软件的环境变量，也不去翻用户家目录里的凭据文件 ——
# 一个独立软件私自找 key 属于越权，用户没同意过。
KEY_ENV_VAR = "PFT_API_KEY"

BUILTIN_BASE = "https://api.deepseek.com"
BUILTIN_MODEL = "deepseek-chat"

# 本程序版本。**改版本时这里和 installer.iss 的 AppVer 要一起改。**
APP_VERSION = "1.0.4"
REPO_SLUG = "NeoHotaru/pretend-foreigner-translator"


def parse_version(s):
    """把 "v1.2.3" / "1.2" 变成 (1, 2, 3) 这种元组，好比较。

    认不出来的返回 (0,)，所以任何怪 version 都不会被当成"更新"。
    """
    out = []
    for part in str(s or "").strip().lstrip("vV").split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def check_latest_release(timeout=20):
    """问一次 GitHub 的最新 release。

    返回 (有没有新版, 最新版本号, 下载页 URL)；任何失败都返回 (False, None, None)。
    **这个函数不许影响启动** —— 所以异常全吞。

    ⚠ 超时原本是 6 秒，实测本机走代理问一次要 6.5 秒 —— 正好卡在边界，
    于是每次都超时、每次都"看起来像没有新版"。改成 20 秒。
    ⚠ 注意:失败时这里【不抛异常也不返回原因】，所以调用方要自己把结果写进日志，
    否则"失败"和"没有新版"无法区分。
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/latest" % REPO_SLUG,
            headers={"User-Agent": "pretend-foreigner/%s" % APP_VERSION,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        tag = (data.get("tag_name") or "").strip()
        url = (data.get("html_url") or "").strip()
        if not tag:
            return False, None, None
        return parse_version(tag) > parse_version(APP_VERSION), tag, url
    except Exception:
        return False, None, None

# ───────────────────────── 语言 ─────────────────────────

LANGS = [
    ("auto", "自动（中 ⇄ 英）"),
    ("zh", "中文（简体）"),
    ("zh-TW", "中文（繁體）"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("ar", "العربية"),
    ("th", "ไทย"),
    ("vi", "Tiếng Việt"),
    ("tr", "Türkçe"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("id", "Bahasa Indonesia"),
]
LANG_LABEL = {c: n for c, n in LANGS}
CODE_OF_LABEL = {n: c for c, n in LANGS}

MODES = [("auto", "自动判断"), ("precise", "精确 precise"), ("casual", "闲聊 casual")]
MODE_CODES = [c for c, _ in MODES]

MEM_MIN, MEM_MAX = 0, 200
BUDGET_MIN, BUDGET_MAX, BUDGET_STEP = 1000, 500000, 1000


def lang_name(code):
    return LANG_LABEL.get(code, code)


def clamp_depth(v, default=8):
    """记忆条数。任何入口读到脏值都不会出错。"""
    try:
        d = int(str(v).strip())
    except Exception:
        return default
    return max(MEM_MIN, min(MEM_MAX, d))


def clamp_budget(v, default=12000):
    """记忆总字数额度。条数管不住的体积用它兜住。"""
    try:
        d = int(str(v).strip())
    except Exception:
        return default
    return max(BUDGET_MIN, min(BUDGET_MAX, d))


def pick_context(history, depth, budget):
    """先按条数取最近的，再按字数从最旧的往回丢，直到塞得下。
    返回 (选中的列表, 实际字数)。"""
    if depth <= 0 or budget <= 0:
        return [], 0
    picked, total = [], 0
    for h in reversed(list(history)[-depth:]):
        cost = len(h.get("src", "")) + len(h.get("out", ""))
        if picked and total + cost > budget:
            break
        picked.append(h)
        total += cost
    picked.reverse()
    return picked, total


# ───────────────────────── 提示词 ─────────────────────────

BASE_PROMPT = """You are a translator working inside a running conversation between a user and an AI assistant.

You will be given a TARGET language, optionally some conversation history for ONE side of the
conversation, and the text to translate.

STEP 1 - detect the SOURCE language of the input (ISO 639-1). If it mixes languages, use whichever dominates.

STEP 2 - decide the output language:
  - if TARGET is "auto": translate into Chinese (zh) when the source is NOT Chinese, and into
    English (en) when the source IS Chinese.
  - otherwise translate into the given TARGET.

STEP 3 - detect the register:
  - "precise": an instruction, task, technical request, spec, or a question expecting an
    accurate answer - anything the reader will act on.
  - "casual": chit-chat, venting, joking, banter, a quick reaction, small talk.

STEP 4 - translate.

Conversation rules:
- The history belongs to ONE side only (either the user or the assistant). Use it to keep
  terminology consistent and to resolve references such as "it", "that", "this one",
  "the previous point". Do NOT copy its content and do NOT let it change the register of
  the current input.
- A short reply like "好" or "ok" must stay short. Do not expand it into a full sentence.

General rules (all languages):
- Output ONLY the translation.
- Keep the length and information content the same. Do not add or drop meaning.
- Keep technical terms exact: API names, flags, filenames, product names and code identifiers
  stay in their original form and are NOT translated.
- Never return the input unchanged. If the input is already in the target language, translate
  it into English instead and report the target you actually used.

precise register:
- Complete words, correct grammar, natural phrasing in the target language.
- No texting abbreviations.
- Must NOT read like machine translation: use the word order and idiom that a native writer
  of that language would use, not a calque of the source language.

casual register:
- Sound like a native speaker of the TARGET language in their 20s-30s texting a friend.
- Use that language's OWN texting conventions and slang, not English ones.
  English: u / ur / bc / tho / gonna / wanna / idk / tbh / ngl / lol / lmao / asap
  Chinese: 哈哈 / 笑死 / 麻了 / 确实 / 绷不住
  Japanese: 草 / w / それな / やばい / まじで
  Korean: ㅋㅋ / ㅇㅇ / 헐 / 대박
  German: hdf / ka    Spanish: jaja / q / xq / tmb
- Natural density, not a parody. Do not force abbreviations into every word.
- Keep the emotion and slang level of the original.

Output STRICT JSON only:
{"source":"<code>","target":"<code>","mode":"precise"|"casual","text":"<the translation>"}
"""


def build_system_prompt(target, forced_mode, context=None, note="", cross_context=None):
    p = BASE_PROMPT + "\n\nTARGET: " + target

    if note and note.strip():
        p += ("\n\nProject note from the user (terminology / background). "
              "Respect preferred terms:\n" + note.strip())

    if cross_context:
        lines = [
            "",
            "The OTHER side's recent turns — this is what the current side is replying to.",
            "Use these ONLY to understand the referent: what \"it\" / \"that\" / \"the above\"",
            "means, and what a short reply like \"yes\" / \"ok\" / \"no\" / \"对\" / \"行\" /",
            "\"好\" is agreeing or disagreeing with. Quote nothing from them.",
            "Do NOT copy their wording, and do NOT let their register change this side's register.",
            "Most recent last:",
        ]
        for h in cross_context:
            lines.append("- [%s] %s   =>   [%s] %s"
                         % (h.get("srcLang", "?"), h.get("src", ""),
                            h.get("tgtLang", "?"), h.get("out", "")))
        p += "\n".join(lines)

    if context:
        lines = ["", "This side's own earlier turns (most recent last):",
                 "Use these for terminology and tone consistency."]
        for h in context:
            lines.append("- [%s->%s] %s  =>  %s"
                         % (h.get("srcLang", "?"), h.get("tgtLang", "?"),
                            h.get("src", ""), h.get("out", "")))
        p += "\n".join(lines)

    if forced_mode == "precise":
        p += "\n\nOVERRIDE: always use the precise register, ignore STEP 3."
    elif forced_mode == "casual":
        p += "\n\nOVERRIDE: always use the casual register, ignore STEP 3."

    return p


# ───────────────────────── 杂项 ─────────────────────────

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S") + "  " + str(msg) + "\n")
    except Exception:
        pass


def read_env_key():
    """内置 DeepSeek 用的 key：只从 PFT_API_KEY 读，读不到返回 None。

    找不到不是错误 —— 公开版本里别人本来就没有这个变量。
    没有就弹首次运行向导，让用户自己选服务商、自己填 key。
    """
    val = os.environ.get(KEY_ENV_VAR)
    if val and val.strip():
        return val.strip()
    return None


def script_kind(text):
    """粗略判断输入用的什么文字系统：han/kana/hangul/cyrillic/arabic/thai/latin/unknown。"""
    groups = [
        ("han", r"[\u4e00-\u9fff\u3400-\u4dbf]"),
        ("kana", r"[\u3040-\u30ff]"),
        ("hangul", r"[\uac00-\ud7af\u1100-\u11ff]"),
        ("cyrillic", r"[\u0400-\u04ff]"),
        ("arabic", r"[\u0600-\u06ff]"),
        ("thai", r"[\u0e00-\u0e7f]"),
        ("latin", r"[A-Za-z]"),
    ]
    best, best_n = "unknown", 0
    for name, pat in groups:
        n = len(re.findall(pat, text))
        if n > best_n:
            best, best_n = name, n
    return best


def parse_reply(raw, fb_src="?", fb_tgt="?"):
    """把模型返回的 JSON 解析成 dict。解析不了就退化成纯文本，绝不抛异常。"""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    src, tgt, mode, text = fb_src, fb_tgt, "?", None
    try:
        o = json.loads(s)
        if isinstance(o, dict) and o.get("text"):
            src = o.get("source") or src
            tgt = o.get("target") or tgt
            mode = o.get("mode") or mode
            text = str(o["text"]).strip()
    except Exception:
        pass

    if text is None:
        m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
        if m:
            try:
                text = json.loads('"' + m.group(1) + '"')
            except Exception:
                text = m.group(1)
        else:
            text = s
        for key, pat in (("source", r'"source"\s*:\s*"([^"]+)"'),
                         ("target", r'"target"\s*:\s*"([^"]+)"'),
                         ("mode", r'"mode"\s*:\s*"([^"]+)"')):
            mm = re.search(pat, s)
            if mm:
                if key == "source":
                    src = mm.group(1)
                elif key == "target":
                    tgt = mm.group(1)
                else:
                    mode = mm.group(1)

    return {"source": src, "target": tgt, "mode": mode, "text": text.strip()}


def load_json(path, default, legacy=None):
    if not os.path.isfile(path) and legacy and os.path.isfile(legacy):
        path = legacy
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("load %s failed: %s" % (path, e))
    return json.loads(json.dumps(default))


def save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log("save %s failed: %s" % (path, e))
        return False


# ───────────────────────── API ─────────────────────────

class ApiError(Exception):
    pass


def url_candidates(base, suffix):
    b = (base or "").strip().rstrip("/")
    if re.search(r"/v\d+$", b):
        return [b + "/" + suffix]
    return [b + "/v1/" + suffix, b + "/" + suffix]


def http_session(use_proxy):
    """trust_env=False：不让系统里的 HTTPS_PROXY 悄悄生效，行为可预测。"""
    s = requests.Session()
    s.trust_env = False
    if use_proxy:
        s.proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    return s


def call_chat(base, key, model, system_prompt, user_text,
              use_proxy=False, timeout=45, max_tokens=900):
    """OpenAI 兼容的 chat/completions。失败抛 ApiError。"""
    if requests is None:
        raise ApiError("没装 requests")
    if not base:
        raise ApiError("没填 Base URL")
    if not key:
        raise ApiError("没填 API Key")
    if not model:
        raise ApiError("没选模型")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 1.0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    sess = http_session(use_proxy)
    last_err = None

    for url in url_candidates(base, "chat/completions"):
        for _attempt in range(2):
            try:
                r = sess.post(url, headers=headers, json=body, timeout=timeout)
            except Exception as e:
                last_err = "连不上：%s" % e
                time.sleep(0.7)
                continue

            if r.status_code == 404:
                last_err = "404（路径不对）"
                break
            if r.status_code >= 400:
                raise ApiError("HTTP %s：%s" % (r.status_code, r.text[:200]))

            try:
                j = r.json()
            except Exception:
                raise ApiError("响应不是 JSON：%s" % r.text[:180])

            if j.get("error"):
                raise ApiError("API 报错：%s" % j["error"].get("message", j["error"]))
            try:
                return j["choices"][0]["message"]["content"]
            except Exception:
                raise ApiError("响应结构不对：%s" % str(j)[:180])

    raise ApiError(last_err or "请求失败")


def list_models(base, key, use_proxy=False, timeout=25):
    """读 OpenAI 兼容的 /models。/v1 带不带都试。"""
    if requests is None:
        raise ApiError("没装 requests")
    headers = {"Authorization": "Bearer " + key}
    sess = http_session(use_proxy)
    last = None
    for url in url_candidates(base, "models"):
        try:
            r = sess.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            last = "连不上：%s" % e
            continue
        if r.status_code == 404:
            last = "404"
            continue
        if r.status_code >= 400:
            raise ApiError("HTTP %s：%s" % (r.status_code, r.text[:160]))
        try:
            j = r.json()
        except Exception:
            raise ApiError("响应不是 JSON")
        arr = j.get("data") or j.get("models") or (j if isinstance(j, list) else None)
        ids = []
        if isinstance(arr, list):
            for m in arr:
                if isinstance(m, str):
                    ids.append(m)
                elif isinstance(m, dict):
                    ids.append(str(m.get("id") or m.get("name") or ""))
        ids = [i for i in ids if i]
        if ids:
            return ids
        last = "列表为空"
    raise ApiError(last or "读不到模型列表")


def call_cli(which, system_prompt, user_text):
    """调本机 codex / claude CLI。prompt 必须走 stdin，作为参数传它们会一直等。"""
    import subprocess

    prompt = system_prompt + "\n\nInput:\n" + user_text
    if which == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check", "-m", "gpt-5.6-luna",
               "-c", 'model_reasoning_effort="low"']
    else:
        cmd = ["claude", "-p"]

    try:
        p = subprocess.run(cmd, input=prompt.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    except FileNotFoundError:
        raise ApiError("找不到 %s 命令" % which)
    except subprocess.TimeoutExpired:
        raise ApiError("%s 超时" % which)

    out = p.stdout.decode("utf-8", errors="replace")
    if re.search(r"usage limit|hit your usage", out):
        raise ApiError("Codex 额度已用完")
    if re.search(r"Not logged in|Please run /login", out):
        raise ApiError("Claude 未登录（需要 Pro）")

    keep = []
    for line in out.splitlines():
        t = line.strip()
        if not t:
            continue
        if re.match(r"^(OpenAI Codex|-{4,}|workdir:|model:|provider:|approval:|sandbox:|"
                    r"reasoning|session id:|user$|tokens used|Reading|ERROR|error)", t):
            continue
        keep.append(t)
    if not keep:
        raise ApiError("%s 没返回译文" % which)
    return "".join(keep)


# ───────────────────────── 免费机器翻译（无需 API Key）─────────────────────────

# 我们的 ISO 代码 -> Google 的代码（大部分一样）
GOOGLE_LANG = {
    "zh": "zh-CN", "zh-TW": "zh-TW", "en": "en", "ja": "ja", "ko": "ko",
    "de": "de", "fr": "fr", "es": "es", "pt": "pt", "it": "it", "ru": "ru",
    "ar": "ar", "th": "th", "vi": "vi", "tr": "tr", "nl": "nl", "pl": "pl",
    "id": "id",
}


def call_google_free(text, target, use_proxy=False, timeout=25):
    """免费机翻。不需要 key，但**要能访问 Google**（国内需挂代理）。

    这是公开版本的兜底：装完就能用，代价是没有语域判定、没有上下文记忆。
    返回和 call_chat 一样是纯文本（这里直接就是译文）。
    """
    if requests is None:
        raise ApiError("没装 requests")

    src = "auto"
    tl = GOOGLE_LANG.get(target) or GOOGLE_LANG.get(target.split("-")[0]) or target
    if tl == "zh-CN":
        tl = "zh-CN"

    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&dt=t&sl=%s&tl=%s&q=%s" % (src, tl, quote(text)))
    sess = http_session(use_proxy)
    try:
        r = sess.get(url, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        raise ApiError("连不上翻译服务（国内用免费机翻需要挂代理）：%s" % e)

    if r.status_code >= 400:
        raise ApiError("机翻 HTTP %s：%s" % (r.status_code, r.text[:120]))
    try:
        data = r.json()
    except Exception:
        raise ApiError("机翻返回的不是 JSON：%s" % r.text[:120])

    parts = []
    for seg in (data[0] or []):
        if seg and seg[0]:
            parts.append(seg[0])
    if not parts:
        raise ApiError("机翻没返回译文")
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else "?"
    return {"text": "".join(parts), "source": detected, "target": tl}


# ───────────────────────── 会话 ─────────────────────────

DEFAULT_CONFIG = {
    "providers": [],
    "activeBackend": "builtin",
    "myLang": "zh",
    "peerLang": "en",
    "mode": "auto",
    "memoryDepth": 8,
    "contextCharBudget": 12000,
    "crossMemoryDepth": 2,      # 允许参照对方最近几条（只为解指代）
    "asrBackend": "sensevoice", # 语音识别后端：sensevoice | whisper
    "asrDevice": None,          # 麦克风编号，None = 系统默认
    "asrWarmup": True,          # 启动后在后台预加载识别模型
    "globalHotkeys": True,      # 全局快捷键开关
    "overlayAlpha": 1.0,        # 悬浮窗透明度
    "overlaySide": "toPeer",    # 悬浮窗上次用的方向
    "overlayPos": None,         # 悬浮窗上次的位置 [x, y]
    "setupDone": False,         # 首次运行向导走过了没
    "googleUseProxy": False,    # 免费机翻要不要走本地代理
}


def new_session(name):
    return {"name": name, "note": "", "toPeer": [], "fromPeer": []}


def use_sandbox_config(dirpath=None):
    """把配置 / 会话文件指到临时目录。

    **写测试或脚本时必须先调这个。** 血的教训：`Translator()` 的
    `save_config()` / `save_sessions()` 默认写的是真实文件，
    测试里随手 new 一个 Translator 再调一次保存，就把用户的会话和设置覆盖了。
    本项目的测试数据就是这么被清掉过一次。

    返回 (config_path, session_path)。
    """
    global CONFIG_FILE, SESSION_FILE
    d = dirpath or os.path.join(os.environ.get("TEMP", "."), "pft_sandbox")
    os.makedirs(d, exist_ok=True)
    CONFIG_FILE = os.path.join(d, "pretend_foreigner.config.json")
    SESSION_FILE = os.path.join(d, "pretend_foreigner.sessions.json")
    for p in (CONFIG_FILE, SESSION_FILE):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass
    return CONFIG_FILE, SESSION_FILE


def is_sandboxed():
    """现在用的是不是沙箱路径。测试里断言一下，防止误伤真数据。"""
    return "pft_sandbox" in CONFIG_FILE or "pft_sandbox" in SESSION_FILE


def default_user_data_dir():
    """用户的配置 / 会话放哪：%APPDATA%\\pretend-foreigner\\

    公开版本会被装进 C:\\Program Files\\ 之类的地方 —— 那里普通用户不可写，
    配置必须放在用户目录里，装到哪个盘都能用。
    """
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "pretend-foreigner")


def use_user_data_dir(dirpath=None):
    """把配置 / 会话指到用户数据目录（默认 %APPDATA%\\pretend-foreigner\\）。

    和 use_sandbox_config() 的两点关键区别：
      1. **绝不删除任何文件** —— 沙箱那个会 os.remove，只能在测试里用
      2. 会把程序旁边的旧配置【复制】过去，老用户不丢设置；原件保留

    只在 main() 里调用，**不要在模块导入时调用** ——
    否则测试一 import 这个模块就会把真实数据搬走。
    """
    global CONFIG_FILE, SESSION_FILE
    d = dirpath or default_user_data_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return CONFIG_FILE, SESSION_FILE     # 建不出来就维持原样，别因为搬家把程序弄坏

    old_cfg, old_ses = CONFIG_FILE, SESSION_FILE
    CONFIG_FILE = os.path.join(d, "pretend_foreigner.config.json")
    SESSION_FILE = os.path.join(d, "pretend_foreigner.sessions.json")

    for old, new in ((old_cfg, CONFIG_FILE), (old_ses, SESSION_FILE)):
        try:
            if (old and os.path.isfile(old) and not os.path.isfile(new)
                    and os.path.abspath(old) != os.path.abspath(new)):
                shutil.copy2(old, new)
        except Exception:
            pass
    return CONFIG_FILE, SESSION_FILE


# ───────────────────────── 后端总入口 ─────────────────────────

class Translator:
    """前端唯一需要打交道的东西。

    典型用法（界面里）：
        t = Translator()
        # 用户点「翻译」时，在工作线程里：
        r = t.translate(text, lane="toPeer")
        # 回到主线程显示 r["text"]

    lane:
        "toPeer"   我说的 -> 译成对方语言（config["peerLang"]）
        "fromPeer" 对方说的 -> 译成我的语言（config["myLang"]）
    """

    def __init__(self, config=None, sessions=None, active=None):
        self.config = config if config is not None else load_json(
            CONFIG_FILE, DEFAULT_CONFIG, LEGACY_CONFIG)
        for k, v in DEFAULT_CONFIG.items():
            self.config.setdefault(k, v)
        self._sanitize_config()

        if sessions is None:
            sdata = load_json(SESSION_FILE, {"active": "", "list": []}, LEGACY_SESSION)
            sessions = sdata.get("list") or []
            if active is None:
                active = sdata.get("active") or ""
        if not sessions:
            sessions = [new_session("会话 1")]
        self.sessions = sessions
        self.active = active or sessions[0]["name"]
        if not any(s["name"] == self.active for s in self.sessions):
            self.active = self.sessions[0]["name"]
        self.current_session()

    # ── 配置 ──

    def _sanitize_config(self):
        """配置文件被手改坏了也能自愈。"""
        c = self.config
        c["memoryDepth"] = clamp_depth(c.get("memoryDepth", 8))
        c["contextCharBudget"] = clamp_budget(c.get("contextCharBudget", 12000))
        c["crossMemoryDepth"] = clamp_depth(c.get("crossMemoryDepth", 2), 2)
        c["myLang"] = c.get("myLang") or "zh"
        c["peerLang"] = c.get("peerLang") or "en"
        if c.get("mode") not in MODE_CODES:
            c["mode"] = "auto"
        if not isinstance(c.get("providers"), list):
            c["providers"] = []

    def save_config(self):
        return save_json(CONFIG_FILE, self.config)

    def save_sessions(self):
        return save_json(SESSION_FILE, {"active": self.active, "list": self.sessions})

    def save_all(self):
        return self.save_config() and self.save_sessions()

    # ── 后端列表 ──

    def backends(self):
        """返回 [(显示名, key)]。key 直接传给 set_backend()。

        显示名会带上可用性标记，公开版本里用户一眼能看出哪些是能用的。
        """
        items = []

        # 只在真的设了 PFT_API_KEY 时才列出来。
        # 踩过：删掉"自动找 key"之后仍无条件列出它，于是没设这个变量的人会看到一个
        # 【列得出来、选了什么也不能用】的死选项（用户当场踩到，问"怎么还有个内置"）。
        if read_env_key():
            items.append(("内置 DeepSeek（环境变量提供）", "builtin"))

        for p in self.config.get("providers", []):
            has_key = bool((p.get("apiKey") or "").strip())
            items.append(("自定义 · %s (%s)%s"
                          % (p.get("name"), p.get("model"),
                             "" if has_key else "  ⚠ 没填 key"),
                          "provider:" + str(p.get("name"))))

        items.append(("免费机翻（无需 key，需能访问 Google）", "google"))
        items.append(("codex（需登录 + 额度）", "codex"))
        items.append(("claude（需 Pro）", "claude"))
        return items

    def backend_available(self, key):
        """这个后端现在能不能用。返回 (能不能用, 原因)。"""
        if key == "google":
            return True, ""
        if key == "builtin":
            if read_env_key():
                return True, ""
            return False, ("没提供 API Key（设 %s 环境变量，"
                           "或在下面添加自己的服务商）" % KEY_ENV_VAR)
        if key == "codex":
            if shutil.which("codex"):
                return True, ""
            return False, "PATH 里没有 codex 命令"
        if key == "claude":
            if shutil.which("claude"):
                return True, ""
            return False, "PATH 里没有 claude 命令"
        if key.startswith("provider:"):
            p = self.get_provider(key[len("provider:"):])
            if not p:
                return False, "找不到这个配置"
            if not (p.get("apiKey") or "").strip():
                return False, "没填 API Key"
            if not (p.get("model") or "").strip():
                return False, "没选模型"
            return True, ""
        return False, "不认识的 backend"

    def has_own_backend(self):
        """用户自己有没有配好一个非免费的后端（本机 key 或填过 key 的自定义服务）。"""
        if read_env_key():
            return True
        for p in self.config.get("providers", []):
            if (p.get("apiKey") or "").strip() and (p.get("model") or "").strip():
                return True
        return False

    def needs_setup(self):
        """要不要弹首次运行向导。

        已经有自己配好的后端就不弹 —— 开发机和老用户都不会被打扰。
        """
        if self.config.get("setupDone"):
            return False
        return not self.has_own_backend()

    def set_backend(self, key):
        self.config["activeBackend"] = key
        self.save_config()

    def active_backend(self):
        key = self.config.get("activeBackend", "google")
        if key not in [k for _, k in self.backends()]:
            key = "google"      # 兜底必须是永远可用的那个，不能指向可能不存在的 builtin
        return key

    def get_provider(self, name):
        for p in self.config.get("providers", []):
            if p.get("name") == name:
                return p
        return None

    def upsert_provider(self, item):
        """item: {name, baseUrl, apiKey, model, useProxy}。同名覆盖。"""
        name = item.get("name")
        provs = self.config.setdefault("providers", [])
        for i, p in enumerate(provs):
            if p.get("name") == name:
                provs[i] = item
                self.save_config()
                return True
        provs.append(item)
        self.save_config()
        return True

    def delete_provider(self, name):
        self.config["providers"] = [p for p in self.config.get("providers", [])
                                    if p.get("name") != name]
        self.save_config()

    # ── 会话 ──

    def session_names(self):
        return [s["name"] for s in self.sessions]

    def current_session(self):
        for s in self.sessions:
            if s["name"] == self.active:
                s.setdefault("note", "")
                s.setdefault("toPeer", [])
                s.setdefault("fromPeer", [])
                return s
        s = new_session(self.active)
        self.sessions.append(s)
        return s

    def switch_session(self, name):
        if any(s["name"] == name for s in self.sessions):
            self.active = name
            self.save_sessions()
            return True
        return False

    def add_session(self, name):
        if any(s["name"] == name for s in self.sessions):
            return False
        self.sessions.append(new_session(name))
        self.active = name
        self.save_sessions()
        return True

    def rename_session(self, old, new):
        for s in self.sessions:
            if s["name"] == old:
                s["name"] = new
                if self.active == old:
                    self.active = new
                self.save_sessions()
                return True
        return False

    def delete_session(self, name):
        if len(self.sessions) <= 1:
            return False
        self.sessions = [s for s in self.sessions if s["name"] != name]
        if self.active == name:
            self.active = self.sessions[0]["name"]
        self.save_sessions()
        return True

    def note(self):
        return self.current_session().get("note", "")

    def set_note(self, text):
        self.current_session()["note"] = (text or "").strip()
        self.save_sessions()

    # ── 记忆 ──

    def memory(self, lane):
        return list(self.current_session().get(lane, []))

    def delete_memory(self, lane, indexes):
        arr = self.current_session().setdefault(lane, [])
        for i in sorted(set(indexes), reverse=True):
            if 0 <= i < len(arr):
                arr.pop(i)
        self.save_sessions()

    def clear_memory(self, lane):
        self.current_session()[lane] = []
        self.save_sessions()

    # ── 设置项 ──

    def set_langs(self, my_lang, peer_lang):
        self.config["myLang"] = my_lang or "zh"
        self.config["peerLang"] = peer_lang or "en"
        self.save_config()

    def set_mode(self, mode):
        self.config["mode"] = mode if mode in MODE_CODES else "auto"
        self.save_config()

    def set_memory(self, depth=None, budget=None, cross=None):
        if depth is not None:
            self.config["memoryDepth"] = clamp_depth(depth)
        if budget is not None:
            self.config["contextCharBudget"] = clamp_budget(budget)
        if cross is not None:
            self.config["crossMemoryDepth"] = clamp_depth(cross, 2)
        self.save_config()

    # ── 翻译 ──

    def target_for(self, lane):
        return (self.config.get("peerLang", "en") if lane == "toPeer"
                else self.config.get("myLang", "zh"))

    def resolve_target(self, lane, text):
        """目标语言和输入语言撞车时纠一下。中英这一对脚本自己纠，
        其他语言交给提示词里那条 never-return-the-input-unchanged。"""
        target = self.target_for(lane)
        kind = script_kind(text)
        if target in ("zh", "zh-TW") and kind == "han":
            return "en"
        if target == "en" and kind == "latin":
            return "zh"
        return target

    def _runner(self, key):
        """返回一个 (system_prompt, user_text) -> 原始字符串 的调用函数。"""
        if key == "google":
            # 免费机翻不认提示词，只认纯文本，所以走另一条路（见 translate）
            return None

        if key == "builtin":
            def run(sp, ut):
                api_key = read_env_key()
                if not api_key:
                    raise ApiError("没提供 API Key（设 %s 环境变量，或改用别的引擎）"
                                   % KEY_ENV_VAR)
                return call_chat(BUILTIN_BASE, api_key, BUILTIN_MODEL, sp, ut, use_proxy=False)
            return run

        if key in ("codex", "claude"):
            return lambda sp, ut: call_cli(key, sp, ut)

        if key.startswith("provider:"):
            p = self.get_provider(key[len("provider:"):])
            if not p:
                raise ApiError("找不到配置 %s" % key)
            return lambda sp, ut: call_chat(p.get("baseUrl"), p.get("apiKey"), p.get("model"),
                                            sp, ut, use_proxy=bool(p.get("useProxy")))

        raise ApiError("后端不对：%s" % key)

    def plan(self, text, lane, mode=None, remember=True):
        """不发请求，只算出这次要用的提示词和统计。调试和自检用。"""
        mode = mode or self.config.get("mode", "auto")
        depth = clamp_depth(self.config.get("memoryDepth", 8))
        budget = clamp_budget(self.config.get("contextCharBudget", 12000))
        target = self.resolve_target(lane, text)

        sess = self.current_session()
        history, chars = pick_context(sess.get(lane, []), depth, budget)

        # 对方最近几条：风格不参与，只为解开"我在回应什么"
        other = "fromPeer" if lane == "toPeer" else "toPeer"
        cross_depth = clamp_depth(self.config.get("crossMemoryDepth", 2), 2)
        cross, cross_chars = pick_context(sess.get(other, []), cross_depth, budget)

        return {
            "backend": self.active_backend(),
            "lane": lane,
            "target": target,
            "mode": mode,
            "system_prompt": build_system_prompt(target, mode, history, self.note(), cross),
            "context": history,
            "ctx_count": len(history),
            "ctx_chars": chars,
            "cross_context": cross,
            "cross_count": len(cross),
            "cross_chars": cross_chars,
            "depth": depth,
            "cross_depth": cross_depth,
            "budget": budget,
            "remember": remember,
        }

    def translate(self, text, lane, mode=None, remember=True):
        """翻译一段文本。**阻塞**，界面请开线程。

        返回 dict:
            text, source, target, mode      译文和判定结果
            backend, lane, elapsed          元信息
            ctx_count, ctx_chars            这次带了多少记忆
            memory_count                    本栏翻完之后的总条数
        """
        text = (text or "").strip()
        if not text:
            raise ApiError("没有内容可翻")
        if lane not in ("toPeer", "fromPeer"):
            raise ApiError("lane 只能是 toPeer 或 fromPeer")

        p = self.plan(text, lane, mode, remember)

        t0 = time.time()
        if p["backend"] == "google":
            # 免费机翻：没有提示词、没有语域、没有上下文，只有译文
            g = call_google_free(text, p["target"],
                                 use_proxy=bool(self.config.get("googleUseProxy")))
            r = {"text": g["text"], "source": g["source"],
                 "target": g["target"], "mode": "literal"}
        else:
            run = self._runner(p["backend"])
            raw = run(p["system_prompt"], text)
            r = parse_reply(raw)
        elapsed = time.time() - t0

        if not r["text"]:
            raise ApiError("没返回内容")

        if remember:
            arr = self.current_session().setdefault(lane, [])
            arr.append({"src": text, "out": r["text"],
                        "srcLang": r["source"], "tgtLang": r["target"]})
            if len(arr) > MEM_MAX:
                del arr[:-MEM_MAX]
            self.save_sessions()

        return {
            "text": r["text"],
            "source": r["source"],
            "target": r["target"],
            "mode": r["mode"],
            "backend": p["backend"],
            "lane": lane,
            "elapsed": elapsed,
            "ctx_count": p["ctx_count"],
            "ctx_chars": p["ctx_chars"],
            "cross_count": p["cross_count"],
            "cross_chars": p["cross_chars"],
            "memory_count": len(self.current_session().get(lane, [])),
        }

    # ── 服务商工具（给设置界面用）──

    def probe_models(self, base, key, use_proxy=False):
        return list_models(base, key, use_proxy)

    def probe_chat(self, base, key, model, use_proxy=False):
        raw = call_chat(base, key, model,
                        build_system_prompt("auto", "auto"), "你好",
                        use_proxy=use_proxy, max_tokens=200)
        return parse_reply(raw)


# ───────────────────────── 命令行自检 ─────────────────────────

def _selftest():
    import sys
    t = Translator()
    print("后端:", [n for n, k in t.backends()])
    print("当前:", t.active_backend())
    print("会话:", t.session_names(), " 当前:", t.active)
    print("语言: 我=%s 对方=%s" % (t.config["myLang"], t.config["peerLang"]))
    print("记忆: %d 条 / %d 字" % (t.config["memoryDepth"], t.config["contextCharBudget"]))
    print()
    cases = [
        ("今天累死了，不想干活了", "toPeer"),
        ("Can you refactor this into a separate module?", "toPeer"),
        ("そのバグ、明日直しておくね", "fromPeer"),
    ]
    for text, lane in cases:
        p = t.plan(text, lane)
        print("  [%s] %s" % (lane, text))
        print("      目标=%s 后端=%s 本栏=%d条/%d字 参照对方=%d条"
              % (p["target"], p["backend"], p["ctx_count"], p["ctx_chars"],
                 p["cross_count"]))
        try:
            r = t.translate(text, lane, remember=False)
            print("      -> %s  (%.1fs, %s/%s)"
                  % (r["text"], r["elapsed"], r["source"], r["mode"]))
        except Exception as e:
            print("      -> 失败:", e)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
