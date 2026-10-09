"""Actual source-box translation via UIA, without any composer or clipboard."""
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
from playwright.sync_api import sync_playwright
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes()
folder=ROOT/'artifacts/input-preview'
C.use_sandbox_config(str(folder/'pft_sandbox_inline'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,asrWarmup=False,
    globalHotkeys=False,selectionButton=False,activeBackend='provider:fixture',providers=[
    dict(name='fixture',apiKey='local-test-fixture',baseUrl='http://example.invalid',model='fixture')]))
session=C.new_session('原位翻译测试')
session['toPeer']=[dict(src='悬浮窗',out='floating island',srcLang='zh',tgtLang='en')]
session['fromPeer']=[dict(src='The floating island looks large.',out='悬浮窗有点大。',srcLang='en',tgtLang='zh')]
C.save_json(C.SESSION_FILE,{'active':session['name'],'list':[session]})
from translate_app import App
from input_target import capture_target,user32,TargetError
from overlay import install_hotkeys
app=App();app.withdraw();app.translate_current_input();controller=app.inline_input
callbacks=[];app.report_callback_exception=lambda *args:callbacks.append(str(args[1]))
u=user32();clip=u.GetClipboardSequenceNumber()
gate=threading.Event();gate.set();calls=[];output='make it smaller lol'
passed=[];error=None
def runner(key):
    def translate(prompt,text):
        calls.append((prompt,text));gate.wait(8)
        return json.dumps(dict(text=output,source='zh',target='en',mode='casual'))
    return translate
def tick(predicate,seconds=10,label='completion'):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.update();controller.pump()
        if predicate():return
        time.sleep(.02)
    from input_target import window_text
    raise AssertionError('Timeout '+label+': '+app.lbl_status.cget('text')+'; foreground='+window_text(u,u.GetForegroundWindow()))
def check(ok,name):
    assert ok,name
    passed.append(name)
HTML='''<!doctype html><meta charset="utf-8"><title>NeoHotaru 原位翻译测试</title>
<style>body{font:20px sans-serif;padding:20px}textarea,[contenteditable]{display:block;
width:85%;height:100px;border:1px solid #777;margin:15px 0;padding:12px}</style>
<h2>本地原位翻译测试 · 不发送</h2><textarea id="plain"></textarea>
<div id="rich" role="textbox" contenteditable="true" class="ProseMirror"></div>
<input id="other"><input id="password" type="password">
<script>window.enters=0;window.state={};document.addEventListener('keydown',e=>{
if(e.key==='Enter'){window.enters++;e.preventDefault()}});
document.addEventListener('input',e=>{window.state[e.target.id]=e.target.value??e.target.innerText})</script>'''
try:
    app.hotkeys=install_hotkeys(app,toggle_hotkey=False,clip_hotkey=False)
    check(3 in app.hotkeys.registered,'Win+Alt+I registered')
    with sync_playwright() as p, patch.object(C.Translator,'_runner',side_effect=runner):
        browser=p.chromium.launch(headless=False,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
            args=['--window-position=760,70','--window-size=850,740','--force-renderer-accessibility'])
        page=browser.new_page(viewport={'width':800,'height':620});page.set_content(HTML)
        def prepare(field,text):
            page.bring_to_front()
            import ctypes
            from ctypes import wintypes
            u.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];u.FindWindowW.restype=wintypes.HWND
            tick(lambda:u.FindWindowW(None,'NeoHotaru 原位翻译测试 - Google Chrome'),label='Chrome title')
            hwnd=u.FindWindowW(None,'NeoHotaru 原位翻译测试 - Google Chrome')
            assert hwnd,'No isolated Chrome window'
            u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            rect=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
            x,y=rect.left+80,rect.top+15
            u.WindowFromPoint.argtypes=[wintypes.POINT];u.WindowFromPoint.restype=wintypes.HWND
            assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==hwnd,'Test title bar obscured'
            u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
            page.evaluate('''([id,text])=>{const e=document.getElementById(id);e.focus();
                if('value' in e)e.value=text;else e.textContent=text}''',[field,text])
            targets=[]
            def capture():
                try:t=capture_target()
                except TargetError:return False
                if 'NeoHotaru 原位翻译测试' in t.title:targets.append(t);return True
                return False
            tick(capture,label='capture browser');return targets[0]
        def value(field):return page.evaluate('id=>{const e=document.getElementById(id);return e.value??e.innerText}',field)
        def hotkey():
            for key in (0x5B,0x12,0x49):u.keybd_event(key,0,0,0)
            for key in (0x49,0x12,0x5B):u.keybd_event(key,0,2,0)
            tick(lambda:controller.current is not None,label='dispatch hotkey')
        for field,text,translated in [('plain','那个再小一点，哈哈。','make it smaller lol'),
            ('rich','行，就这样😄','sounds good 😄')]:
            output=translated;prepare(field,text);hotkey();tick(lambda:controller.current is None)
            check(value(field)==translated,'原输入框直接替换 '+field+' '+repr(translated))
            check(page.evaluate('id=>window.state[id]',field)==translated,'触发编辑器input事件 '+field)
            check(page.evaluate('document.activeElement.id')==field,'焦点留在原输入框 '+field)
            check(app.input_composer is None,'没有打开另一输入面板')
        check('looks large' in calls[0][0] and 'floating island' in calls[0][0],'沿用两侧上下文')
        check(page.evaluate('window.enters')==0,'整个流程没有Enter或发送事件')
        check(len(app.t.memory('toPeer'))==3,'每次成功替换只记忆一次')
        memory=len(app.t.memory('toPeer'))
        output='first line\nsecond line 😄';prepare('plain','第一行\n第二行');hotkey();tick(lambda:controller.current is None)
        check(value('plain')=='第一行\n第二行' and len(app.t.memory('toPeer'))==memory,'多行译文明确提示手动粘贴，原文不变')
        output='make it smaller lol'

        gate.clear();count=len(calls);prepare('plain','旧稿');hotkey();tick(lambda:len(calls)>count)
        page.evaluate("document.querySelector('#plain').value='用户刚改的新稿'")
        gate.set();tick(lambda:controller.current is None)
        check(value('plain')=='用户刚改的新稿' and len(app.t.memory('toPeer'))==memory,'请求期间改稿不覆盖、不记忆')

        gate.clear();count=len(calls);prepare('rich','旧富文本');hotkey();tick(lambda:len(calls)>count)
        page.evaluate("document.querySelector('#other').focus()")
        gate.set();tick(lambda:controller.current is None)
        check(value('rich')=='旧富文本' and value('other')=='','同窗口另一个输入框不会被误写')
        check(len(app.t.memory('toPeer'))==memory,'焦点变化失败不记忆')

        gate.clear();count=len(calls);prepare('plain','取消的原稿');hotkey();tick(lambda:len(calls)>count)
        controller.cancel();gate.set()
        deadline=time.monotonic()+.3;tick(lambda:time.monotonic()>=deadline)
        check(value('plain')=='取消的原稿' and len(app.t.memory('toPeer'))==memory,'取消后迟到译文不回填')
        check(u.GetClipboardSequenceNumber()==clip,'剪贴板完全不变')
        check(not callbacks,'无Tk回调异常')
        browser.close()
except Exception as exc:error=str(exc)
finally:
    gate.set();app.on_close()
    result=dict(ok=error is None,passed=passed,error=error,real_user_data_unchanged=hashes()==before)
    (folder/'inline-browser-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if error or hashes()!=before:sys.exit(1)
