# -*- coding: utf-8 -*-
"""
voice_input.py  —  录音 + 调用识别进程

两块东西：
    Recorder   麦克风录音，写 16kHz 单声道 wav（ASR 最喜欢的格式）
    AsrClient  常驻的识别子进程，说一句转一句，模型不用重复加载

为什么要子进程见 asr_worker.py 头部说明（OpenMP 冲突 + 模型常驻）。

用法：
    rec = Recorder()
    rec.start()
    ...
    wav = rec.stop()
    asr = AsrClient()              # 第一次会自动加载模型，慢
    text = asr.transcribe(wav)
    asr.close()
"""

import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "asr_worker.py")

TARGET_SR = 16000          # SenseVoice / Whisper 都吃 16k


# ───────────────────────── 设备 ─────────────────────────

def list_input_devices():
    """返回 [(编号, 名称, 声道数, 默认采样率)]。没有 sounddevice 就返回空。"""
    try:
        import sounddevice as sd
    except Exception:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d.get("name", "?"), d["max_input_channels"],
                            int(d.get("default_samplerate", 48000))))
    except Exception:
        pass
    return out


def default_input_device():
    try:
        import sounddevice as sd
        d = sd.query_devices(kind="input")
        return d.get("index", None)
    except Exception:
        return None


# ───────────────────────── 录音 ─────────────────────────

class Recorder:
    """录音到临时 wav。start() / stop() / cancel()。

    优先 16kHz 单声道；设备不支持就按默认采样率录，停止时重采样。
    重采样用 scipy（已装），不依赖 ffmpeg。
    """

    def __init__(self, samplerate=TARGET_SR, device=None, channels=1):
        self.want_sr = samplerate
        self.device = device
        self.channels = channels
        self._stream = None
        self._frames = []
        self._sr = samplerate
        self._lock = threading.Lock()
        self._peak = 0.0          # 平滑后的当前电平（画条用）
        self._max_peak = 0.0      # 整段录音的最大电平（判断是不是静音）
        self._nframes = 0         # 已录帧数（算时长）
        self._tmpdir = os.path.join(tempfile.gettempdir(), "pft_voice")
        os.makedirs(self._tmpdir, exist_ok=True)

    @property
    def recording(self):
        return self._stream is not None

    def level(self):
        """0.0-1.0 的当前音量，画电平条用。"""
        with self._lock:
            return self._peak

    def max_peak(self):
        """整段录音里最大的音量。用来判断"这段是不是根本没声音"。"""
        with self._lock:
            return self._max_peak

    def seconds(self):
        """已经录了多久。"""
        with self._lock:
            return self._nframes / float(self._sr or TARGET_SR)

    def start(self):
        import sounddevice as sd

        if self.recording:
            return
        self._frames = []
        self._peak = 0.0
        self._max_peak = 0.0
        self._nframes = 0

        # 先试目标采样率，不行退回设备默认
        tried = []
        for sr in (self.want_sr, None):
            try:
                if sr is None:
                    info = sd.query_devices(self.device, kind="input")
                    sr = int(info["default_samplerate"])
                stream = sd.InputStream(
                    samplerate=sr, channels=self.channels, device=self.device,
                    dtype="int16", blocksize=0, callback=self._cb)
                stream.start()
                self._stream = stream
                self._sr = sr
                return
            except Exception as e:
                tried.append("%s: %s" % (sr, e))
        raise RuntimeError("打不开麦克风 → " + " | ".join(tried))

    def _cb(self, indata, frames, t, status):
        with self._lock:
            self._frames.append(bytes(indata))
            self._nframes += frames
            try:
                import numpy as np
                peak = float(np.abs(np.frombuffer(bytes(indata), dtype=np.int16)).max()) / 32768.0
                self._peak = max(self._peak * 0.7, peak)
                if peak > self._max_peak:
                    self._max_peak = peak
            except Exception:
                pass

    def _finish(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            data = b"".join(self._frames)
            self._frames = []
        return data

    def cancel(self):
        self._finish()

    def stop(self):
        """停止并落盘，返回 wav 路径。没录到东西返回 None。"""
        data = self._finish()
        if not data:
            return None

        sr = self._sr
        if sr != self.want_sr:
            data = self._resample(data, sr, self.want_sr)
            sr = self.want_sr

        # 目录可能被外部删掉（清理工具、系统临时文件回收都会干这事），
        # 所以每次落盘前都确认一次，不能只在 __init__ 里建。
        os.makedirs(self._tmpdir, exist_ok=True)
        path = os.path.join(self._tmpdir, "rec_%d.wav" % int(time.time() * 1000))
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(data)
        return path

    @staticmethod
    def _resample(data, src_sr, dst_sr):
        try:
            import numpy as np
            from scipy.signal import resample_poly
            from math import gcd
            a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            g = gcd(int(src_sr), int(dst_sr))
            up, down = int(dst_sr // g), int(src_sr // g)
            y = resample_poly(a, up, down)
            y = np.clip(y, -32768, 32767).astype(np.int16)
            return y.tobytes()
        except Exception:
            return data          # 重采样失败就把原样的交给识别进程


# ───────────────────────── 识别子进程 ─────────────────────────

class AsrClient:
    """常驻识别进程的客户端。

    transcribe() 是阻塞的（首次还要等模型加载），界面请开线程调。
    """

    def __init__(self, backend=None, python_exe=None, whisper_size="small",
                 model_dir=None, load_timeout=180):
        self.backend = backend
        self.python = python_exe or sys.executable or "python"
        self.whisper_size = whisper_size
        self.model_dir = model_dir
        self.load_timeout = load_timeout

        self.proc = None
        self.ready_backend = None
        self.load_error = None
        self._q = queue.Queue()
        self._reader = None
        self._lock = threading.Lock()

    # — 生命周期 —

    def start(self, wait=True):
        if self.proc and self.proc.poll() is None:
            return True

        if getattr(sys, "frozen", False):
            # 打包后 sys.executable 是 exe 自己，而且 asr_worker.py【不在磁盘上】
            #（PyInstaller 把它编进了 PYZ）—— 所以让同一个 exe 用 --asr-worker
            # 把自己当工作进程跑。不这么写的话，语音会静默失效。
            cmd = [sys.executable, "--asr-worker", "--whisper-size", self.whisper_size]
        else:
            cmd = [self.python, WORKER, "--whisper-size", self.whisper_size]
        if self.backend:
            cmd += ["--backend", self.backend]
        if self.model_dir:
            cmd += ["--model-dir", self.model_dir]

        creation = 0
        if os.name == "nt":
            creation = 0x08000000          # CREATE_NO_WINDOW，别弹黑框

        # PYTHONUTF8 / PYTHONIOENCODING 显式传给子进程，
        # 不能指望调用环境里有（从桌面双击启动时就没有）。
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        self._q = queue.Queue()
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=HERE, creationflags=creation,
                encoding="utf-8", errors="replace", bufsize=1, env=env)
        except Exception as e:
            self.load_error = "启动识别进程失败: %s" % e
            return False

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        if not wait:
            return True

        line = self._wait_line(self.load_timeout)
        if line is None:
            rc = self.proc.poll()
            self.load_error = ("识别进程没就绪（退出码 %s）。"
                               "多半是模型没下载完或缺依赖。" % rc)
            self.stop()
            return False
        if line.startswith("READY"):
            parts = line.split()
            self.ready_backend = parts[1] if len(parts) > 1 else "?"
            self.load_error = None
            return True
        self.load_error = "识别进程返回异常: %s" % line
        return False

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line.rstrip("\r\n"))
        except Exception:
            pass
        finally:
            self._q.put(None)              # 结束标记

    def _wait_line(self, timeout):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        p = self.proc
        self.proc = None
        if not p:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write("QUIT\n")
                    p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=3)
                except Exception:
                    p.kill()
        except Exception:
            pass

    # — 识别 —

    def transcribe(self, wav_path, timeout=90):
        if not (self.proc and self.proc.poll() is None):
            if not self.start():
                raise RuntimeError(self.load_error or "识别进程没起来")

        with self._lock:
            try:
                self.proc.stdin.write("FILE %s\n" % wav_path)
                self.proc.stdin.flush()
            except Exception as e:
                raise RuntimeError("跟识别进程通信失败: %s" % e)

        line = self._wait_line(timeout)
        if line is None:
            raise RuntimeError("识别超时（%d 秒）" % timeout)
        if line.startswith("OK"):
            return line[2:].strip()
        if line.startswith("ERR"):
            raise RuntimeError(line[3:].strip())
        raise RuntimeError("意外返回: %s" % line)

    def warm_up(self):
        """后台预热，界面一打开就调，用户第一次点麦克风时模型已经在了。"""
        def go():
            try:
                self.start()
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()


# ───────────────────────── 命令行自测 ─────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--wav", help="识别这个文件")
    ap.add_argument("--backend", default=None)
    ap.add_argument("--record", type=float, default=0, help="录 N 秒再识别")
    a = ap.parse_args()

    if a.list_devices:
        print("默认输入:", default_input_device())
        for i, n, ch, sr in list_input_devices():
            print("  [%d] %s  %dch  %dHz" % (i, n, ch, sr))
        raise SystemExit(0)

    if a.record:
        rec = Recorder()
        print("开始录 %.0f 秒…" % a.record)
        rec.start()
        time.sleep(a.record)
        wav = rec.stop()
        print("录到:", wav)

    if a.wav:
        c = AsrClient(backend=a.backend)
        if not c.start():
            print("启动失败:", c.load_error)
            raise SystemExit(2)
        print("后端:", c.ready_backend)
        t0 = time.time()
        print("识别:", c.transcribe(a.wav))
        print("耗时: %.2fs" % (time.time() - t0))
        c.stop()
