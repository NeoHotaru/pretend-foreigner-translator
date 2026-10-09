"""Editable selections translate in place; readonly messages become peer context."""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from input_notice import show_nonactivating, hide_nonactivating
from input_target import capture_target, TargetError, target_has_focus
from island_window import ISLAND_BG, ISLAND_PRESSED, ISLAND_TEXT, work_area
from ui_kit import brand_icon, FONT_UI


class SelectionPopup(tk.Toplevel):
    def __init__(self, app, activate):
        super().__init__(app)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=ISLAND_BG)
        self.title('假装翻译 · 选区按钮')
        self.visible = False
        self._activate = activate
        self._pressed = False
        self._icon = brand_icon(self, 24)
        self.body = tk.Frame(self, bg=ISLAND_BG, padx=14, cursor='hand2')
        self.body.pack(fill='both', expand=True)
        self.logo = tk.Label(self.body, image=self._icon, bg=ISLAND_BG, cursor='hand2')
        self.logo.pack(side='left', padx=(0, 9))
        self.label = tk.Label(self.body, text='假装翻译', font=FONT_UI,
                              bg=ISLAND_BG, fg=ISLAND_TEXT, cursor='hand2')
        self.label.pack(side='left')
        for widget in (self, self.body, self.logo, self.label):
            widget.bind('<Enter>', lambda e: self._color(ISLAND_PRESSED))
            widget.bind('<Leave>', lambda e: self._color(ISLAND_BG) if not self._pressed else None)
            widget.bind('<ButtonPress-1>', self._down)
            widget.bind('<ButtonRelease-1>', self._up)

    def _color(self, color):
        for widget in (self, self.body, self.logo, self.label):
            widget.configure(bg=color)

    def _down(self, _event):
        self._pressed = True
        self._color(ISLAND_PRESSED)
        return 'break'

    def _up(self, event):
        pressed, self._pressed = self._pressed, False
        self._color(ISLAND_BG)
        if pressed and (self.winfo_rootx() <= event.x_root < self.winfo_rootx()+self.winfo_width()
                        and self.winfo_rooty() <= event.y_root < self.winfo_rooty()+self.winfo_height()):
            self._activate()
        return 'break'

    def show(self, bounds, reference=False):
        self.label.configure(text='参考这句' if reference else '假装翻译')
        x,y,w,h = bounds
        width,height = 142,44
        left,top,right,bottom = work_area(round(x+w),round(y+h),
                                         (self.winfo_screenwidth(), self.winfo_screenheight()))
        px = max(left+8,min(round(x+w)-width,right-width-8))
        py = round(y+h)+8
        if py+height > bottom-8:
            py = round(y)-height-8
        py = max(top+8,min(py,bottom-height-8))
        show_nonactivating(self, px, py, width, height, radius=12)
        self.visible = True

    def hide(self):
        if self.visible:
            hide_nonactivating(self)
        self.visible = False
        self._pressed = False


class SelectionButton:
    def __init__(self, app):
        self.app = app
        self.popup = SelectionPopup(app, self.activate)
        self.snapshot = self.target = None
        self.events = queue.Queue()
        self.stopped = threading.Event()
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        powershell = Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        args = [str(powershell),'-NoLogo','-NoProfile','-NonInteractive',
            '-ExecutionPolicy','Bypass','-File',str(base/'assets/selection-watch.ps1'),
            '-OwnerProcess',str(os.getpid())]
        from translator_core import is_sandboxed
        if is_sandboxed():
            args += ['-WindowPrefix','NeoHotaru ']
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._read,daemon=True,name='selection-button').start()

    def _read(self):
        try:
            for line in self.process.stdout:
                if self.stopped.is_set():
                    return
                self.events.put(json.loads(line))
        except (OSError, ValueError):
            self.events.put({'type':'error'})

    def pump(self):
        latest = None
        try:
            while True:
                latest = self.events.get_nowait()
        except queue.Empty:
            pass
        if self.app.busy:
            self.popup.hide()
            self.snapshot = self.target = None
            return
        if latest is None:
            if self.target:
                try:
                    if not target_has_focus(self.target):
                        self.clear()
                except TargetError:
                    self.clear()
            return
        if latest['type'] != 'selection':
            self.clear()
            if latest['type'] == 'error':
                self.app.status('选区按钮暂未启动；仍可使用悬浮窗或输入框翻译。','bad')
            return
        snapshot = latest['snapshot']
        try:
            target = capture_target()
        except TargetError:
            self.clear()
            return
        if target.window != snapshot['window'] or target.process_id != snapshot['process_id']:
            self.clear()
            return
        self.snapshot, self.target = snapshot, target
        self.popup.show(snapshot['bounds'], reference=snapshot.get('purpose')=='reference')

    def clear(self):
        self.snapshot = self.target = None
        self.popup.hide()

    def activate(self):
        snapshot,target = self.snapshot,self.target
        self.clear()
        if snapshot and target:
            if snapshot.get('purpose')=='reference':
                self.app.reference_peer_message(target, snapshot)
            else:
                self.app.translate_current_input(target=target,selection=snapshot)

    def stop(self):
        self.stopped.set()
        self.clear()
        if self.process.poll() is None:
            self.process.terminate()
        self.popup.destroy()
