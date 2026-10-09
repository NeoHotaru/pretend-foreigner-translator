"""A received message becomes peer context and gets its own reading bubble."""
import copy
import math
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont, ttk
from dataclasses import dataclass, field
from input_automation import InputAutomation
from input_composer import context_signature
from input_notice import show_nonactivating, hide_nonactivating
from input_target import TargetError, user32
from island_window import work_area
from ui_kit import C_BG as ISLAND_BG, C_SURFACE as ISLAND_FIELD, C_TEXT as ISLAND_TEXT, C_MUTED as ISLAND_MUTED, C_BAD
from translator_core import Translator, lang_name
from ui_kit import brand_icon, text_surface, FONT_TEXT, FONT_HEAD, FONT_SMALL, FONT_READING


@dataclass
class ReferenceRequest:
    target: object
    selection: dict
    session: dict
    signature: str
    translator: object
    cancelled: object = field(default_factory=threading.Event)
    entry: object = None
    text: str = ''
    result: object = None
    pending: bool = True


class ReferenceBubble(tk.Toplevel):
    def __init__(self, app, owner):
        super().__init__(app)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=ISLAND_BG)
        self.title('假装翻译 · 对方消息译文')
        self.visible = False
        self.owner = owner
        self.body = tk.Frame(self, bg=ISLAND_BG, padx=18, pady=15)
        self.body.pack(fill='both', expand=True)
        row = tk.Frame(self.body,bg=ISLAND_BG);row.pack(fill='x')
        self._icon = brand_icon(self,24)
        tk.Label(row,image=self._icon,bg=ISLAND_BG).pack(side='left',padx=(0,9))
        tk.Label(row,text='对方说了什么',bg=ISLAND_BG,fg=ISLAND_TEXT,
                 font=FONT_HEAD).pack(side='left')
        self._action(row,'×',owner.cancel).pack(side='right')
        self.context = tk.Label(self.body,text='',bg=ISLAND_BG,fg=ISLAND_MUTED,
                                font=FONT_SMALL,anchor='w',wraplength=424,justify='left')
        self.context.pack(fill='x',pady=(10,8))
        self.original = tk.Label(self.body,text='',bg=ISLAND_BG,fg=ISLAND_MUTED,
            font=FONT_SMALL,anchor='w',justify='left',wraplength=424)
        
        self.target_label = tk.Label(self.body,text='对方的意思',bg=ISLAND_BG,fg=ISLAND_TEXT,
                                      font=FONT_SMALL,anchor='w')
        self.target_label.pack(fill='x',pady=(0,5))
        surface,self.output = text_surface(self.body,height=6,font=FONT_READING,bg=ISLAND_FIELD,fg=ISLAND_TEXT)
        surface.pack(fill='both',expand=True)
        self.output.configure(state='disabled')
        self.original.pack(fill='x',pady=(12,0))
        self.status = tk.Label(self.body,text='',bg=ISLAND_BG,fg=ISLAND_MUTED,font=FONT_SMALL,
                                wraplength=424,anchor='w',justify='left')
        self.status.pack(fill='x',pady=(10,8))
        footer = tk.Frame(self.body,bg=ISLAND_BG);footer.pack(fill='x')
        self.copy = self._action(footer,'复制译文',owner.copy_translation);self.copy.pack(side='left')
        self.retry = self._action(footer,'重试翻译',owner.retry)
        self.context_button = self._action(footer,'查看上下文',lambda:owner.view_context())
        self._action(footer,'关闭',owner.cancel).pack(side='right')

    def _action(self, master, text, command):
        return ttk.Button(master,text=text,command=command,style='Quiet.TButton',takefocus=False)

    def show(self, request, status, translation='', retry=False, error=False):
        recorded=any(entry is request.entry for entry in request.session.get('fromPeer',[]))
        state='已加入对方消息' if recorded else '参考消息已移除' if request.entry is not None else '正在核对选中的消息'
        self.context.configure(text='会话：%s · %s' % (request.session['name'],state))
        original = request.text or request.selection['selected']
        self.original.configure(text='原文：'+original[:160]+('…' if len(original)>160 else ''))
        target=request.result['target'] if request.result else request.translator.resolve_target('fromPeer',original)
        self.target_label.configure(text='对方的意思 · '+lang_name(target))
        display=translation or ('译文暂未获取，参考原文仍保留。' if error and recorded else
                               '本次未取得译文，请重新选择消息。' if error else '正在翻译对方的话…')
        font=tkfont.Font(self,font=FONT_READING)
        lines=sum(max(1,math.ceil(font.measure(line)/378)) for line in display.split('\n'))
        self.output.configure(height=min(8,max(2,lines)))
        self.output.configure(state='normal');self.output.delete('1.0','end')
        self.output.insert('1.0',display)
        self.output.configure(state='disabled')
        self.status.configure(text=status,fg=C_BAD if error else ISLAND_MUTED)
        self.copy.configure(state='normal' if translation else 'disabled')
        self.retry.pack(side='left',padx=8) if retry else self.retry.pack_forget()
        if request.result and request.result.get('context_usage'):
            self.context_button.pack(side='left',padx=(8,0))
        else:self.context_button.pack_forget()
        self.update_idletasks()
        width,height = 460,min(600,max(280,self.body.winfo_reqheight()))
        x,y,w,h=request.selection['bounds']
        left,top,right,bottom=work_area(round(x+w),round(y+h),(self.winfo_screenwidth(),self.winfo_screenheight()))
        px=max(left+8,min(round(x+w)-width,right-width-8))
        py=round(y+h)+12
        if py+height>bottom-8:py=round(y)-height-12
        py=max(top+8,min(py,bottom-height-8))
        show_nonactivating(self,px,py,width,height,radius=16)
        self.visible=True

    def hide(self):
        if self.visible:hide_nonactivating(self)
        self.visible=False


class PeerReference:
    def __init__(self, app):
        self.app=app
        self.current=None
        self.events=queue.Queue()
        self.automation=InputAutomation()
        self.bubble=ReferenceBubble(app,self)

    def start(self, target, selection):
        if self.app.busy or self.app.recording_target is not None:
            self.app.status('先完成当前翻译或录音。');return
        self.cancel()
        session=self.app.t.current_session()
        request=ReferenceRequest(target,copy.deepcopy(selection),session,context_signature(self.app.t),
            Translator(config=copy.deepcopy(self.app.t.config),sessions=[copy.deepcopy(session)],active=session['name']))
        self.current=request;self.app.busy+=1
        self.bubble.show(request,'选中的原文会作为对方消息加入这个会话。')
        def read():
            try:
                source=self.automation.call(target,'read-reference',request.cancelled,selection=selection)
                self.events.put((request,'read',source['selected']))
            except Exception as error:self.events.put((request,'error',str(error)))
        threading.Thread(target=read,daemon=True,name='peer-reference-read').start()

    def _valid(self, request):
        return (self.current is request and not request.cancelled.is_set()
            and self.app.t.current_session() is request.session and context_signature(self.app.t)==request.signature)

    def _translate(self, request):
        def worker():
            try:
                result=request.translator.translate(request.text,'fromPeer',mode='precise',remember=False)
                self.events.put((request,'translated',result))
            except Exception as error:self.events.put((request,'error',str(error)))
        threading.Thread(target=worker,daemon=True,name='peer-reference-translate').start()

    def pump(self):
        try:
            while True:
                request,stage,data=self.events.get_nowait()
                if self.current is not request or request.cancelled.is_set():continue
                if stage=='read':
                    if not self._valid(request):
                        self._finish(request,'会话或设置已变化，未加入本次参考。',error=True);continue
                    request.text=data
                    try:
                        request.entry,saved=self.app.t.remember_peer_reference(data,session=request.session)
                    except Exception as error:
                        self._finish(request,str(error),error=True);continue
                    history=request.translator.current_session()['fromPeer']
                    if history and history[-1].get('src')==data.strip():history.pop()
                    request.signature=context_signature(self.app.t)
                    self.app.sync_views()
                    self.bubble.show(request,'已记录对方原话，正在翻译。' if saved else '对方原话已加入本次会话，但尚未保存；正在翻译。')
                    self._translate(request)
                elif stage=='translated':
                    if not self._valid(request):
                        self._finish(request,'会话或上下文已变化，本次译文未写入；可回到原会话重试。',error=True,retry=True);continue
                    request.result=data
                    try:
                        saved=self.app.t.complete_peer_reference(request.entry,data,session=request.session)
                    except Exception as error:
                        self._finish(request,str(error),translation=data['text'],error=True);continue
                    self.app.sync_views()
                    if not saved:
                        status='译文已完成，参考消息暂未保存。'
                    elif data.get('backend')=='google':
                        status='已加入对方消息；当前免费机翻不使用上下文。'
                    elif not self.app.t.config.get('crossMemoryDepth',2):
                        status='已加入对方消息；开启参照对方消息后，回复翻译会使用它。'
                    else:
                        status='已加入对方消息。你接着回复时，会用它作参考。'
                    self._finish(request,status,translation=data['text'])
                else:
                    self._finish(request,'翻译失败：'+data,translation='',error=True,retry=request.entry is not None)
        except queue.Empty:pass
        if self.current and self.bubble.visible and user32().GetForegroundWindow()!=self.current.target.window:
            self.bubble.hide()

    def _finish(self, request, status, translation='', error=False, retry=False):
        if request.pending:self.app.busy=max(0,self.app.busy-1)
        request.pending=False
        if request.result:
            self.app.record_translation_context(request.result,request.session,request.text,origin='reference')
        self.bubble.show(request,status,translation,retry,error)
        self.app.status(status,'bad' if error else 'ok')

    def view_context(self):
        if self.current and self.current.session is self.app.t.current_session():
            self.app.open_translation_context('fromPeer',owner=self.bubble)
        else:self.app.status('请切回这条参考消息所属的会话，再查看。')

    def retry(self):
        old=self.current
        if not old or old.pending or self.app.busy:return
        if self.app.t.current_session() is not old.session:
            self.app.status('先切回会话「%s」再重试。'%old.session['name']);return
        if not any(entry is old.entry for entry in old.session['fromPeer']):
            self.app.status('参考消息已移除，请重新选择。');return
        session=copy.deepcopy(old.session)
        session['fromPeer']=[copy.deepcopy(entry) for entry in old.session['fromPeer'] if entry is not old.entry]
        request=ReferenceRequest(old.target,old.selection,old.session,context_signature(self.app.t),
            Translator(config=copy.deepcopy(self.app.t.config),sessions=[session],active=session['name']),entry=old.entry,text=old.text)
        self.current=request;self.app.busy+=1
        self.bubble.show(request,'对方原话已保留，正在重试翻译。')
        self._translate(request)

    def copy_translation(self):
        if self.current and self.current.result:
            self.app.copy_text(self.current.result['text'])

    def cancel(self):
        if self.current:
            self.current.cancelled.set();self.automation.cancel()
            if self.current.pending:self.app.busy=max(0,self.app.busy-1)
            self.current=None
        self.bubble.hide()
