"""Translate a draft where the user typed it; never move focus or press send."""
import copy
import queue
import threading
import time
from dataclasses import dataclass, field
from input_automation import InputAutomation
from input_composer import context_signature
from input_target import TargetError, modifiers_released, ime_is_composing
from translator_core import Translator


@dataclass
class InlineRequest:
    target: object
    session: object
    signature: str
    translator: object
    cancelled: object = field(default_factory=threading.Event)
    original: str = ''
    identity: str = ''
    result: object = None
    committing: bool = False
    selection: object = None
    text: str = ''


class InlineInput:
    def __init__(self, app):
        self.app = app
        self.current = None
        self.events = queue.Queue()
        self.automation = InputAutomation()
        self.notice = None
        self.position = None

    def _status(self, text, error=False):
        self.app.status(text, 'bad' if error else 'info')
        if self.notice is None:
            from input_notice import InputNotice
            self.notice = InputNotice(self.app)
        self.notice.show(text, self.position, error, pending=self.current is not None)
        overlay = getattr(self.app, 'overlay', None)
        if overlay is not None:
            overlay.pill_status.configure(text='失败' if error else '已翻译' if '已替换' in text else '翻译中')
            overlay.lbl_hint.configure(text=text)

    def start(self, target=None, reason=None, selection=None):
        if self.current:
            if not self.current.committing:
                self.cancel()
                self._status('已取消输入框翻译，原文保持不变。')
            return
        if target is None:
            from overlay import input_key_pair, key_name
            self._status(reason or '选中文字，点击旁边的「假装翻译」。也可按 %s 翻译整个输入框。' % key_name(*input_key_pair(self.app)))
            return
        if self.app.busy or self.app.recording_target is not None:
            self._status('先完成当前翻译或录音。')
            return
        session = self.app.t.current_session()
        request = InlineRequest(target, session, context_signature(self.app.t),
            Translator(config=copy.deepcopy(self.app.t.config), sessions=[copy.deepcopy(session)], active=session['name']))
        request.selection = selection
        self.current = request
        self.position = target.position
        if selection:
            x,y,w,h = selection['bounds']
            self.position = (round(x+w),round(y+h))
        self.app.busy += 1
        self._status('正在翻译选中文字，完成后只替换选区。' if selection else
                     '正在翻译原输入框；英文出现后再发送。再次按快捷键可取消。')

        def worker():
            try:
                deadline = time.monotonic()+2
                while not modifiers_released():
                    if request.cancelled.is_set() or time.monotonic() >= deadline:
                        raise TargetError('请松开快捷键后再翻译。')
                    time.sleep(.03)
                if ime_is_composing(target.focus):
                    raise TargetError('先确认拼音候选，再翻译整句话。')
                source = self.automation.call(target, 'read-selection' if selection else 'read',
                                              request.cancelled, **({'selection': selection} if selection else {}))
                request.original, request.identity = source['value'], source['identity']
                request.text = source['selected'] if selection else request.original
                if not request.text.strip():
                    raise TargetError('先在当前输入框写好中文，再按快捷键。')
                if len(request.text) > 12000:
                    raise TargetError('原输入框内容太长，请分段翻译。')
                if request.cancelled.is_set():
                    return
                request.result = request.translator.translate(request.text, 'toPeer', remember=False)
                self.events.put((request, 'translated', None))
            except Exception as error:
                self.events.put((request, 'error', str(error)))
        threading.Thread(target=worker, daemon=True, name='inline-translate').start()

    def _valid(self, request):
        return (self.current is request and not request.cancelled.is_set()
                and self.app.t.current_session() is request.session
                and context_signature(self.app.t) == request.signature)

    def pump(self):
        try:
            while True:
                request, stage, error = self.events.get_nowait()
                if self.current is not request:
                    continue
                if stage == 'translated':
                    if not self._valid(request):
                        self._finish(request, '会话或设置已变化，未覆盖原输入框。', True)
                        continue
                    request.committing = True
                    def commit(req=request):
                        try:
                            self.automation.call(req.target, 'replace', req.cancelled, identity=req.identity,
                                original=req.original, translation=req.result['text'],
                                **({'selection': req.selection} if req.selection else {}))
                            self.events.put((req, 'replaced', None))
                        except Exception as exc:
                            self.events.put((req, 'error', str(exc)))
                    threading.Thread(target=commit, daemon=True, name='inline-replace').start()
                elif stage == 'replaced':
                    try:
                        saved = self.app.t.remember_translation(request.text, request.result, session=request.session)
                    except Exception:
                        saved = False
                    self.app.record_translation_context(request.result,request.session,request.text,origin='inline')
                    self.app.sync_views()
                    self._finish(request, '已替换为译文，请确认后照常发送。' if saved else
                                 '已替换为译文，但记忆未保存；请确认后照常发送。')
                else:
                    self._finish(request, error, True)
        except queue.Empty:
            pass

    def _finish(self, request, text, error=False):
        if self.current is request:
            self.current = None
            self.app.busy = max(0, self.app.busy-1)
            self._status(text, error)

    def cancel(self):
        if self.current:
            self.current.cancelled.set()
            self.automation.cancel()
            self.current = None
            self.app.busy = max(0, self.app.busy-1)
        if self.notice is not None:
            self.notice.hide()
