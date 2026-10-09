"""Compose a sentence, preview it, then explicitly insert into the captured app."""
import copy
import hashlib
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from input_draft import InputDraft
from input_target import (TargetError, PartialInsertError, ime_is_composing,
                          insert_text, modifiers_released, restore_target, target_has_focus)
from island_window import ISLAND_BG, ISLAND_TEXT, ISLAND_MUTED, ISLAND_FIELD, work_area
from translator_core import Translator, lang_name
from ui_kit import FONT_UI, FONT_SMALL, FONT_TEXT, brand_icon, text_surface


def context_signature(translator):
    config = translator.config
    keys = ('activeBackend', 'myLang', 'peerLang', 'mode', 'memoryDepth',
            'crossMemoryDepth', 'contextCharBudget', 'providers', 'googleUseProxy')
    data = {'config': {key: config.get(key) for key in keys},
            'session': translator.current_session()}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


class InputComposer(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg=ISLAND_BG)
        self.title('假装外国人 · 翻译输入')
        self.app = app
        self.draft = InputDraft()
        self.target = None
        self.opened = False
        self.busy = False
        self.inserting = False
        self.results = queue.Queue()
        self._insert_timer = None
        self._internal_edit = False
        self._rounded_size = None
        self._build()
        self.bind('<Escape>', lambda event: self.cancel())
        self.bind('<Control-Return>', lambda event: self.request_preview())
        self.bind('<Control-Shift-Return>', lambda event: self.confirm_insert())
        self.bind('<FocusOut>', self._focus_left, add='+')
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Map>', lambda event: self.after_idle(self._round_window) if event.widget is self else None, add='+')

    def _round_window(self):
        import ctypes
        from ctypes import wintypes
        try:
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            g.CreateRoundRectRgn.restype = wintypes.HANDLE
            g.DeleteObject.argtypes = [wintypes.HANDLE]
            u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
            hwnd = u.GetAncestor(self.winfo_id(), 2)
            size = (hwnd, self.winfo_width(), self.winfo_height())
            if size == self._rounded_size or size[1] < 3 or size[2] < 3:
                return
            region = g.CreateRoundRectRgn(0, 0, size[1]+1, size[2]+1, 28, 28)
            if region:
                if u.SetWindowRgn(hwnd, region, True):
                    self._rounded_size = size
                else:
                    g.DeleteObject(region)
        except (AttributeError, OSError, tk.TclError):
            pass

    def _focus_left(self, event):
        # Browser fields may share a native HWND. Require a new explicit target
        # after leaving the composer, even if the same app is activated again.
        if event.widget is self and self.opened and not self.inserting and self.target:
            import ctypes
            import os
            from ctypes import wintypes
            from input_target import user32
            u = user32()
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
            if pid.value == os.getpid():
                return
            self.target = None
            self.lbl_target.configure(text='填入位置已取消，请回到目标输入框重新按快捷键')
            self._status('切换了窗口；译文保留，重新选择位置后可填入。')
            self._buttons()

    def _build(self):
        body = tk.Frame(self, bg=ISLAND_BG, padx=20, pady=17)
        body.pack(fill='both', expand=True)
        top = tk.Frame(body, bg=ISLAND_BG)
        top.pack(fill='x')
        self._icon = brand_icon(self, 24)
        tk.Label(top, image=self._icon, bg=ISLAND_BG).pack(side='left', padx=(0, 9))
        tk.Label(top, text='翻译输入', font=('Microsoft YaHei UI', 13, 'bold'),
                 fg=ISLAND_TEXT, bg=ISLAND_BG).pack(side='left')
        tk.Button(top, text='×', command=self.cancel, bg=ISLAND_BG, fg=ISLAND_MUTED,
                  activebackground=ISLAND_FIELD, activeforeground=ISLAND_TEXT,
                  relief='flat', bd=0, font=('Segoe UI', 17), padx=7).pack(side='right')
        self.lbl_context = tk.Label(body, text='', fg=ISLAND_MUTED, bg=ISLAND_BG,
                                    font=FONT_SMALL, anchor='w')
        self.lbl_context.pack(fill='x', pady=(9, 3))
        self.lbl_target = tk.Label(body, text='', fg=ISLAND_TEXT, bg=ISLAND_BG,
                                   font=FONT_SMALL, anchor='w', wraplength=520, justify='left')
        self.lbl_target.pack(fill='x', pady=(0, 12))
        tk.Label(body, text='你的原话', font=FONT_SMALL, fg=ISLAND_MUTED,
                 bg=ISLAND_BG, anchor='w').pack(fill='x')
        frame, self.txt_in = text_surface(body, height=4, font=FONT_TEXT,
                                          bg=ISLAND_FIELD, fg=ISLAND_TEXT, insertbackground=ISLAND_TEXT)
        frame.pack(fill='x', pady=(5, 10))
        self.txt_in.bind('<<Modified>>', self._source_changed)
        row = tk.Frame(body, bg=ISLAND_BG)
        row.pack(fill='x')
        self.btn_preview = ttk.Button(row, text='翻译预览', style='Go.TButton', command=self.request_preview)
        self.btn_preview.pack(side='left')
        tk.Label(row, text='Ctrl+Enter 翻译', font=FONT_SMALL, fg=ISLAND_MUTED,
                 bg=ISLAND_BG).pack(side='left', padx=12)
        tk.Label(body, text='译文预览', font=FONT_SMALL, fg=ISLAND_MUTED,
                 bg=ISLAND_BG, anchor='w').pack(fill='x', pady=(15, 0))
        frame, self.txt_out = text_surface(body, height=4, font=FONT_TEXT,
                                           bg=ISLAND_FIELD, fg=ISLAND_TEXT)
        frame.pack(fill='x', pady=(5, 10))
        self.txt_out.configure(state='disabled')
        for widget in (self.txt_in, self.txt_out):
            widget.bind('<Control-Return>', lambda event: self.request_preview())
            widget.bind('<Control-Shift-Return>', lambda event: self.confirm_insert())
        self.lbl_status = tk.Label(body, text='写好一句话，再翻译。', fg=ISLAND_MUTED,
                                   bg=ISLAND_BG, font=FONT_SMALL, wraplength=520,
                                   justify='left', anchor='w')
        self.lbl_status.pack(fill='x', pady=(0, 10))
        row = tk.Frame(body, bg=ISLAND_BG)
        row.pack(fill='x')
        self.btn_insert = ttk.Button(row, text='填入原输入框', style='Go.TButton',
                                     command=self.confirm_insert, state='disabled')
        self.btn_insert.pack(side='right')
        self.btn_copy = ttk.Button(row, text='复制译文', command=self.copy_preview, state='disabled')
        self.btn_copy.pack(side='left')
        ttk.Button(row, text='取消', command=self.cancel).pack(side='left', padx=8)
        self.update_idletasks()
        self._width = 560
        self._height = max(490, body.winfo_reqheight())

    def show(self, target=None, reason=None):
        if self.inserting:
            return
        self.target = target
        self.opened = True
        self.lbl_context.configure(text='会话：%s · 目标：%s' % (
            self.app.t.active, lang_name(self.app.t.target_for('toPeer'))))
        title = target.title if target else ''
        self.lbl_target.configure(text=('填入：' + title[:56]) if target else '先点击目标输入框，再按翻译输入快捷键')
        point = target.position if target else (self.winfo_pointerx(), self.winfo_pointery())
        left, top, right, bottom = work_area(*point, (self.winfo_screenwidth(), self.winfo_screenheight()))
        x = max(left+8, min(point[0], right-self._width-8))
        y = point[1]+18 if point[1]+18+self._height <= bottom-8 else point[1]-self._height-18
        y = max(top+8, min(y, bottom-self._height-8))
        self.geometry('%dx%d+%d+%d' % (self._width, self._height, x, y))
        if self.draft.result and not self._ready():
            self.draft.discard()
            self._set_output('')
        if reason:
            self._status(reason)
        elif self.draft.result:
            self._status('确认译文后填入；不会替你发送。')
        else:
            self._status('中文先留在这里，预览后再填入原窗口。')
        self._buttons()
        self.deiconify()
        self.lift()
        self.focus_force()
        self.txt_in.focus_set()

    def _ready(self):
        return self.draft.can_insert(self.app.t.current_session(), context_signature(self.app.t))

    def _status(self, text, error=False):
        self.lbl_status.configure(text=text, fg='#ffb6ae' if error else ISLAND_MUTED)

    def _set_output(self, text):
        self.txt_out.configure(state='normal')
        self.txt_out.delete('1.0', 'end')
        if text:
            self.txt_out.insert('1.0', text)
        self.txt_out.configure(state='disabled')

    def _buttons(self):
        ready = self._ready()
        self.btn_preview.configure(state='disabled' if self.busy or self.inserting else 'normal',
                                   text='翻译中…' if self.busy else '翻译预览')
        self.btn_insert.configure(state='normal' if ready and self.target and not self.inserting else 'disabled')
        self.btn_copy.configure(state='normal' if ready and not self.inserting else 'disabled')

    def _source_changed(self, _event=None):
        if not self.txt_in.edit_modified():
            return
        self.txt_in.edit_modified(False)
        if self._internal_edit:
            return
        if self.draft.edit(self.txt_in.get('1.0', 'end-1c')):
            self._set_output('')
            self._status('原话已改，写完后重新翻译。')
            self._buttons()

    def request_preview(self):
        if self.busy or self.inserting or self.app.busy or self.app.recording_target is not None:
            self._status('先完成当前翻译或录音。')
            return 'break'
        focused = self.focus_get()
        if focused and ime_is_composing(focused.winfo_id()):
            self._status('先确认拼音候选，再翻译整句话。')
            return 'break'
        self.draft.edit(self.txt_in.get('1.0', 'end-1c'))
        session = self.app.t.current_session()
        try:
            request = self.draft.begin(session, context_signature(self.app.t))
        except ValueError as error:
            self._status(str(error))
            return 'break'
        snapshot = Translator(config=copy.deepcopy(self.app.t.config),
                              sessions=[copy.deepcopy(session)], active=session['name'])
        plan = snapshot.plan(request.text, 'toPeer', remember=False)
        self.busy = True
        self.app.busy += 1
        self._set_output('')
        self._status('免费机翻正在翻译，不使用上下文。' if plan['backend']=='google' else
                     '翻译中… 已带入你的前文%d条、对方消息%d条。' % (plan['ctx_count'], plan['cross_count']))
        self._buttons()

        def worker():
            try:
                result = snapshot.translate(request.text, 'toPeer', remember=False)
            except Exception as error:
                self.results.put((request, None, error))
            else:
                self.results.put((request, result, None))

        threading.Thread(target=worker, daemon=True, name='input-preview').start()
        return 'break'

    def pump(self):
        try:
            while True:
                request, result, error = self.results.get_nowait()
                self.busy = False
                self.app.busy = max(0, self.app.busy-1)
                if not self.opened:
                    continue
                if error:
                    if self.draft.pending is request:
                        self.draft.discard()
                        self._status('翻译失败：%s' % error, True)
                elif self.draft.accept(request, result, self.app.t.current_session(), context_signature(self.app.t)):
                    self._set_output(result['text'])
                    self._status('预览就绪 · 确认后填入原输入框，不自动发送。')
                else:
                    self._status('原话、设置或会话已变化，请重新翻译。')
                self._buttons()
        except queue.Empty:
            pass
        if self.opened and not self.busy and self.draft.result and not self._ready():
            self.draft.discard()
            self._set_output('')
            self._status('会话或上下文已变化，请重新翻译。')
            self._buttons()

    def confirm_insert(self):
        if self.inserting or not self.target or not self._ready():
            self._status('先获得当前原话的译文，再选择要填入的输入框。')
            return 'break'
        self.inserting = True
        self._buttons()
        deadline = time.monotonic()+2
        self._wait_release(deadline)
        return 'break'

    def _wait_release(self, deadline):
        self._insert_timer = None
        if not self.opened or not self._ready():
            self._insert_failed('原话或会话已变化，未填入。')
            return
        if not modifiers_released():
            if time.monotonic() >= deadline:
                self._insert_failed('请松开快捷键后再填入。')
            else:
                self._insert_timer = self.after(30, lambda: self._wait_release(deadline))
            return
        try:
            self.target.validate()
            self.withdraw()
            if not restore_target(self.target):
                raise TargetError('没能回到原窗口；请点原输入框，再按翻译输入快捷键')
        except TargetError as error:
            self._insert_failed(str(error))
            return
        self._insert_timer = self.after(70, self._finish_insert)

    def _finish_insert(self):
        self._insert_timer = None
        if not self._ready():
            self._insert_failed('原话或会话已变化，未填入。')
            return
        try:
            insert_text(self.target, self.draft.result['text'])
        except PartialInsertError as error:
            self.draft.discard()
            self._insert_failed(str(error))
            return
        except TargetError as error:
            self._insert_failed(str(error))
            return
        # Insertion has succeeded: clear readiness before saving, preventing retry.
        request, result = self.draft.ready, self.draft.result
        self.draft.discard()
        try:
            saved = self.app.t.remember_translation(request.text, result, session=request.session)
        except Exception:
            saved = False
        self.app.sync_views()
        self.inserting = False
        self.opened = False
        self.target = None
        self._internal_edit = True
        self.txt_in.delete('1.0', 'end')
        self.txt_in.edit_modified(False)
        self._internal_edit = False
        self.draft.edit('')
        self._set_output('')
        self.app.status('译文已填入，确认后照常发送。' if saved else '译文已填入，但记忆暂未保存；可稍后重试保存。',
                        'ok' if saved else 'bad')

    def _insert_failed(self, message):
        self.inserting = False
        self.deiconify()
        self.lift()
        self._status(message, True)
        self._buttons()

    def copy_preview(self):
        if self._ready():
            self.app.copy_text(self.draft.result['text'])
            self._status('已复制；也可以手动粘贴到原输入框。')

    def cancel(self):
        if self._insert_timer is not None:
            self.after_cancel(self._insert_timer)
            self._insert_timer = None
        self.inserting = False
        self.opened = False
        self.draft.discard()
        self._set_output('')
        self.withdraw()
        target, self.target = self.target, None
        if target:
            try:
                restore_target(target)
            except TargetError:
                pass
        return 'break'
