"""Windows UI Automation bridge: reads and replaces the exact focused input."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from input_target import TargetError, target_has_focus


class InputAutomation:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None

    def cancel(self):
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def call(self, target, action, cancelled, **data):
        if cancelled.is_set():
            raise TargetError('已取消')
        if not target_has_focus(target):
            raise TargetError('输入位置已改变，中文保留在原处。')
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        script = base / 'assets' / 'input-automation.ps1'
        powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        args = [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
                '-ExecutionPolicy', 'Bypass', '-File', str(script)]
        request = json.dumps(dict(action=action, window=target.window, **data), ensure_ascii=False)
        process = None
        try:
            with self._lock:
                if cancelled.is_set():
                    raise TargetError('已取消')
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
                self._process = process
            output, _ = process.communicate(request, timeout=10)
            response = json.loads(output.strip())
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise TargetError('输入框响应超时，请检查原文；不会自动重试。')
        except (OSError, ValueError):
            raise TargetError('没能读取或更新输入框，请检查原文；不会自动重试。')
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        if not response.get('ok'):
            code = response.get('error', '')
            if 'changed' in code.lower():
                raise TargetError('输入位置或原文已变化，本次未覆盖，请重新翻译。')
            if 'does not support' in code:
                raise TargetError('这个输入框暂不支持直接翻译；可用原来的悬浮窗。')
            if 'Multiline' in code:
                raise TargetError('多行译文暂不支持原位替换，原文保持不变；请用悬浮窗翻译并粘贴。')
            raise TargetError('没能更新输入框，请检查原文；不会自动重试。')
        return response
