"""Cancellable provider checks. Credentials travel over stdin, never argv."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


class ProviderProbe:
    def __init__(self):
        self.events = queue.Queue()
        self.current = None

    def start(self, kind, values):
        self.cancel()
        args = ([sys.executable, '--provider-probe'] if getattr(sys, 'frozen', False)
                else [sys.executable, str(Path(__file__).resolve())])
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        ticket = object()
        self.current = (ticket, process)
        payload = json.dumps(dict(kind=kind, **values), ensure_ascii=False)
        def work():
            try:
                stdout, _stderr = process.communicate(payload)
                if process.returncode:
                    raise RuntimeError('检测进程未能完成，请重试。')
                result = json.loads(stdout)
            except Exception as error:
                result = dict(ok=False, error=str(error))
            self.events.put((ticket, result))
        threading.Thread(target=work, daemon=True, name='provider-probe').start()
        return ticket

    def poll(self):
        while True:
            try:
                ticket, result = self.events.get_nowait()
            except queue.Empty:
                return None
            if self.current and self.current[0] is ticket:
                self.current = None
                return result

    def cancel(self):
        job, self.current = self.current, None
        if job and job[1].poll() is None:
            try:
                job[1].terminate()
            except ProcessLookupError:
                pass


def main():
    # A windowed PyInstaller executable sets Python's standard streams to None,
    # even when the parent supplied pipes. Reopen the inherited Win32 handles.
    if sys.platform=='win32':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        get_handle=ctypes.windll.kernel32.GetStdHandle
        get_handle.argtypes=[wintypes.DWORD];get_handle.restype=wintypes.HANDLE
        for name,number,mode,flags in [('stdin',-10,'r',os.O_RDONLY),('stdout',-11,'w',os.O_WRONLY)]:
            if getattr(sys,name) is None:
                fd=msvcrt.open_osfhandle(get_handle(number),flags|os.O_BINARY)
                setattr(sys,name,os.fdopen(fd,mode,encoding='utf-8'))
    from translator_core import list_models, call_chat, build_system_prompt, parse_reply
    try:
        request = json.load(sys.stdin)
        if request['kind']=='models':
            value = list_models(request['base'], request['key'], request['proxy'])
        elif request['kind']=='chat':
            value = parse_reply(call_chat(request['base'], request['key'], request['model'],
                build_system_prompt('auto','auto'), '你好', use_proxy=request['proxy'], max_tokens=200))
        else:
            raise ValueError('未知的检测类型。')
        result = dict(ok=True, value=value)
    except Exception as error:
        result = dict(ok=False, error=str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    sys.stdout.flush()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
