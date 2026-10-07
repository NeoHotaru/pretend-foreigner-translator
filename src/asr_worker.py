# -*- coding: utf-8 -*-
"""
asr_worker.py  —  语音识别工作进程

为什么要单独开一个进程：
    1. torch / ctranslate2 / sherpa-onnx 各带一份 OpenMP 运行时，
       同一个进程里加载就会撞（实测 "OMP: Error #15 ... libiomp5md.dll"）。
       分开跑，各自干净。
    2. 模型常驻内存，说一句转一句，不用每次重新加载。
    3. 识别崩了不会带崩界面。

协议（stdin 一行一条命令，stdout 一行一条结果，都是 UTF-8）：
    命令            返回
    PING         -> READY <backend>         探活
    FILE <path>  -> OK <文本>               识别一个 wav 文件
                    ERR <原因>
    INFO         -> INFO <backend> <模型路径>
    QUIT         -> BYE                     退出

后端：
    sensevoice    sherpa-onnx + SenseVoiceSmall（中文最准，首选）
    whisper       faster-whisper（兜底，中文一般但多语言稳）

直接用命令行测试：
    python asr_worker.py --backend sensevoice --wav some.wav
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 必须显式把标准流钉成 UTF-8。
# Windows 上 stdout 接管道时默认用系统区域编码（中文系统是 cp936），
# 父进程按 UTF-8 解码就会全成乱码 —— 而且从桌面双击启动时不会继承
# 任何 PYTHONIOENCODING，所以这个坑一定会踩到（真踩过）。
for _stream in ("stdin", "stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
MODELS_DIR = os.path.join(HERE, "models")          # 兼容扁平布局
HOTWORDS_FILE = os.path.join(MODELS_DIR, "hotwords.txt")


def model_candidates():
    """按顺序找 SenseVoice 模型目录，返回第一个装齐的。

    故意不写死一个绝对路径：这个包要能被挪到任何地方跑
    （打包进 codex-work 时就是这样，源码在 src/、模型在 ../models/）。
    """
    cands = [
        os.environ.get("PFT_MODEL_DIR"),                       # 环境变量优先
        os.path.join(HERE, "..", "models", MODEL_NAME),        # 包布局：src/ 和 models/ 平级
        os.path.join(HERE, "models", MODEL_NAME),              # 扁平布局
        os.path.join(os.path.expanduser("~"), ".cache", "pft", MODEL_NAME),
        os.path.join(os.path.expanduser("~"), ".cache", "pft", "models", MODEL_NAME),
    ]
    out = []
    for c in cands:
        if c:
            c = os.path.normpath(c)
            if c not in out:
                out.append(c)
    return out


def find_model_dir():
    """找到可用的模型目录；找不到返回 None。"""
    for d in model_candidates():
        model = os.path.join(d, "model.int8.onnx")
        if not os.path.isfile(model):
            model = os.path.join(d, "model.onnx")
        if os.path.isfile(model) and os.path.isfile(os.path.join(d, "tokens.txt")):
            return d
    return None


def log(msg):
    """日志走 stderr，绝不污染 stdout 的协议通道。"""
    sys.stderr.write("[asr] %s\n" % msg)
    sys.stderr.flush()


# ───────────────────────── 读 wav ─────────────────────────

def read_wav(path):
    """返回 (采样率, float32 单声道波形)。

    sherpa-onnx 1.13 没有 read_wave 辅助函数，只有 stream.accept_waveform(rate, samples)，
    所以 wav 要自己读。
    """
    import wave as wavelib
    import numpy as np

    with wavelib.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())

    if sw == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError("不支持的位深: %d 字节" % sw)

    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return sr, a


# ───────────────────────── 后端一：sherpa-onnx + SenseVoice ─────────────────────────

class SenseVoiceBackend:
    name = "sensevoice"

    def __init__(self, model_dir=None, threads=None):
        import sherpa_onnx

        d = model_dir or find_model_dir()
        if not d:
            raise RuntimeError(
                "找不到 SenseVoice 模型。找过这些地方：\n  " +
                "\n  ".join(model_candidates()) +
                "\n下载地址见 docs/CORE_API.md，或设环境变量 PFT_MODEL_DIR 指过去。")
        model = os.path.join(d, "model.int8.onnx")
        if not os.path.isfile(model):
            model = os.path.join(d, "model.onnx")
        tokens = os.path.join(d, "tokens.txt")
        if not os.path.isfile(model) or not os.path.isfile(tokens):
            raise RuntimeError("模型目录不全：%s" % d)

        self.dir = d
        if threads is None:
            threads = max(2, min(8, (os.cpu_count() or 4) // 2))

        # 注意：from_sense_voice 的签名里没有 hotwords_file / hotwords_score
        # （那两个属于 paraformer / transducer），传了会 TypeError，所以不传。
        t0 = time.time()
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model,
            tokens=tokens,
            num_threads=threads,
            use_itn=True,          # 逆文本规整：三百 -> 300，自动加标点
            language="auto",       # zh / en / ja / ko / yue 自动判
            debug=False,
            provider="cpu",
        )
        log("SenseVoice 加载完成 %.1fs  threads=%d" % (time.time() - t0, threads))

    def transcribe(self, wav_path):
        sr, samples = read_wav(wav_path)
        s = self.rec.create_stream()
        s.accept_waveform(sr, samples)     # 采样率不一致时 sherpa 内部会重采样
        self.rec.decode_stream(s)
        return (s.result.text or "").strip()


# ───────────────────────── 后端二：faster-whisper ─────────────────────────

class WhisperBackend:
    name = "whisper"

    def __init__(self, size="small", device="auto", compute="auto"):
        from faster_whisper import WhisperModel

        if device == "auto":
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"

        t0 = time.time()
        self.model = WhisperModel(size, device=device, compute_type=compute)
        log("faster-whisper %s 加载完成 %.1fs  device=%s" % (size, time.time() - t0, device))

    def transcribe(self, wav_path):
        segs, _info = self.model.transcribe(
            wav_path, language=None, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            beam_size=5, condition_on_previous_text=False)
        return "".join(s.text for s in segs).strip()


# ───────────────────────── 工厂 ─────────────────────────

def make_backend(name, **kw):
    if name == "sensevoice":
        return SenseVoiceBackend(**kw)
    if name == "whisper":
        return WhisperBackend(**kw)
    raise RuntimeError("不认识的后端: %s" % name)


def pick_backend(prefer=None):
    """按可用性挑一个。sensevoice 优先，因为中文准得多。"""
    order = [prefer] if prefer else ["sensevoice", "whisper"]
    last = None
    for name in order:
        try:
            return make_backend(name)
        except Exception as e:
            log("%s 不可用：%s" % (name, e))
            last = e
    raise RuntimeError("没有可用的识别后端：%s" % last)


# ───────────────────────── 主循环 ─────────────────────────

def serve(backend):
    out = sys.stdout
    out.write("READY %s\n" % backend.name)
    out.flush()
    log("就绪，等待命令")

    for line in sys.stdin:
        cmd = (line or "").strip()
        if not cmd:
            continue

        if cmd == "PING":
            out.write("READY %s\n" % backend.name)

        elif cmd == "INFO":
            d = getattr(backend, "dir", None)
            out.write("INFO %s %s\n" % (backend.name, d or "default"))

        elif cmd.startswith("FILE "):
            path = cmd[5:].strip()
            if not os.path.isfile(path):
                out.write("ERR 找不到文件 %s\n" % path)
            else:
                try:
                    t0 = time.time()
                    text = backend.transcribe(path)
                    log("%s  %.2fs  %s" % (os.path.basename(path), time.time() - t0,
                                           text[:60]))
                    out.write("OK %s\n" % (text if text else ""))
                except Exception as e:
                    out.write("ERR 识别失败: %s\n" % e)

        elif cmd == "QUIT":
            out.write("BYE\n")
            out.flush()
            return

        else:
            out.write("ERR 不认识的命令: %s\n" % cmd[:40])

        out.flush()

    log("stdin 关闭，退出")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=None,
                    choices=["sensevoice", "whisper", "auto"], help="识别后端")
    ap.add_argument("--model-dir", default=None, help="SenseVoice 模型目录")
    ap.add_argument("--whisper-size", default="small", help="whisper 模型大小")
    ap.add_argument("--wav", default=None, help="一次性识别一个文件后退出（测试用）")
    ap.add_argument("--threads", type=int, default=None)
    a = ap.parse_args()

    try:
        if a.backend == "sensevoice":
            backend = make_backend("sensevoice", model_dir=a.model_dir, threads=a.threads)
        elif a.backend == "whisper":
            backend = make_backend("whisper", size=a.whisper_size)
        else:
            backend = pick_backend(a.backend if a.backend != "auto" else None)
    except Exception as e:
        sys.stderr.write("启动失败: %s\n" % e)
        return 2

    if a.wav:
        try:
            print(backend.transcribe(a.wav))
            return 0
        except Exception as e:
            sys.stderr.write("识别失败: %s\n" % e)
            return 3

    serve(backend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
