"""Real selection discovery and mouse-only replacement in isolated editors."""
import ctypes
import hashlib
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
from playwright.sync_api import sync_playwright
from PIL import ImageGrab
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes()
folder=ROOT/'artifacts/input-preview'
C.use_sandbox_config(str(folder/'pft_sandbox_selection'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,asrWarmup=False,
    globalHotkeys=False,selectionButton=True,activeBackend='provider:fixture',providers=[
    dict(name='fixture',apiKey='local-test-fixture',baseUrl='http://example.invalid',model='fixture')]))
session=C.new_session('选区按钮测试')
session['toPeer']=[dict(src='悬浮窗',out='floating island',srcLang='zh',tgtLang='en')]
session['fromPeer']=[dict(src='The floating island looks large.',out='悬浮窗有点大。',srcLang='en',tgtLang='zh')]
C.save_json(C.SESSION_FILE,{'active':session['name'],'list':[session]})
from translate_app import App
from input_target import user32
app=App();app.withdraw()
callbacks=[];app.report_callback_exception=lambda *args:callbacks.append(str(args[1]))
u=user32();clip=u.GetClipboardSequenceNumber();calls=[];gate=threading.Event();gate.set()
passed=[];error=None;output='make it smaller lol'
def runner(key):
    def translate(prompt,text):
        calls.append((prompt,text));gate.wait(8)
        return json.dumps(dict(text=output,source='zh',target='en',mode='casual'))
    return translate
def tick(predicate,seconds=12,label='completion'):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.update()
        if predicate():return
        time.sleep(.02)
    from input_target import window_text
    raise AssertionError('Timeout '+label+': '+app.lbl_status.cget('text')+'; foreground='+window_text(u,u.GetForegroundWindow())+'; callbacks='+str(callbacks))
def check(ok,name):
    assert ok,name
    passed.append(name)
HTML='''<!doctype html><meta charset="utf-8"><title>NeoHotaru 选区按钮测试</title>
<style>body{font:20px sans-serif;padding:25px}textarea,[contenteditable]{display:block;
width:85%;height:100px;border:1px solid #777;margin:30px 0;padding:12px}</style>
<h2>只替换选中文字 · 本地测试</h2><textarea id="plain"></textarea>
<div id="rich" contenteditable="true" role="textbox" class="ProseMirror"></div>
<input id="other"><textarea id="readonly" readonly>不会修改的只读内容</textarea>
<input id="password" type="password"><script>window.state={};window.enters=0;
document.addEventListener('input',e=>window.state[e.target.id]=e.target.value??e.target.innerText);
document.addEventListener('keydown',e=>{if(e.key==='Enter'){window.enters++;e.preventDefault()}})</script>'''
try:
    with sync_playwright() as p,patch.object(C.Translator,'_runner',side_effect=runner):
        browser=p.chromium.launch(headless=False,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
            args=['--window-position=720,70','--window-size=900,850','--force-renderer-accessibility'])
        page=browser.new_page(viewport={'width':850,'height':730});page.set_content(HTML);page.bring_to_front()
        u.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];u.FindWindowW.restype=wintypes.HWND
        u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        u.WindowFromPoint.argtypes=[wintypes.POINT];u.WindowFromPoint.restype=wintypes.HWND
        tick(lambda:u.FindWindowW(None,'NeoHotaru 选区按钮测试 - Google Chrome'),label='browser title')
        hwnd=u.FindWindowW(None,'NeoHotaru 选区按钮测试 - Google Chrome')
        rect=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect));x,y=rect.left+80,rect.top+15
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==hwnd
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        tick(lambda:app.selection_button is not None,label='watcher startup')
        button=app.selection_button
        def select(field,text,selected,occurrence=1):
            page.evaluate('''([id,text,selected,occurrence])=>{const e=document.getElementById(id);e.focus();
                let start=text.indexOf(selected);for(let n=1;n<occurrence;n++)start=text.indexOf(selected,start+selected.length);
                const end=start+selected.length;
                if('value' in e){e.value=text;e.setSelectionRange(start,end)}
                else{e.textContent=text;const r=document.createRange();r.setStart(e.firstChild,start);
                r.setEnd(e.firstChild,end);const s=getSelection();s.removeAllRanges();s.addRange(r)}}''',[field,text,selected,occurrence])
            tick(lambda:button.popup.visible and button.snapshot and button.snapshot['value']==text,label='selection discovery')
        def click():
            assert button.popup.visible
            wrapper=u.GetAncestor(button.popup.winfo_id(),2)
            r=wintypes.RECT();u.GetWindowRect(wrapper,ctypes.byref(r));x,y=(r.left+r.right)//2,(r.top+r.bottom)//2
            assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==wrapper
            u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
            tick(lambda:app.inline_input is not None and app.inline_input.current is not None)
        def value(field):return page.evaluate('id=>{const e=document.getElementById(id);return e.value??e.innerText}',field)
        for field,text,selection,translated in [
            ('plain','保留前文｜那个再小一点，哈哈。｜保留后文','那个再小一点，哈哈。','make it smaller lol'),
            ('rich','😄前文｜行，就这样｜后文😄','行，就这样','sounds good 😄'),
            ('plain','重复｜小一点｜小一点｜后文','小一点','smaller')]:
            output=translated;previous_calls=len(calls);select(field,text,selection,2 if text.startswith('重复') else 1)
            check(u.GetForegroundWindow()==hwnd,'显示按钮不抢焦点 '+field)
            check(len(calls)==previous_calls,'选择文字不自动调用翻译 '+field)
            if field=='plain' and selection.startswith('那个'):
                sx,sy,sw,sh=button.snapshot['bounds']
                page.evaluate("document.querySelector('#plain').setSelectionRange(0,0)")
                tick(lambda:not button.popup.visible)
                x,y=round(sx+1),round(sy+sh/2)
                assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==hwnd
                u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0)
                for n in range(1,9):
                    u.SetCursorPos(round(sx+1+(sw-2)*n/8),y);time.sleep(.02)
                u.mouse_event(4,0,0,0,0)
                tick(lambda:button.popup.visible and button.snapshot and button.snapshot['selected']==selection)
                check(button.snapshot['selected']==selection,'真实鼠标拖选自动出现按钮')
                wrapper=u.GetAncestor(button.popup.winfo_id(),2);r=wintypes.RECT();u.GetWindowRect(wrapper,ctypes.byref(r))
                ImageGrab.grab(bbox=(r.left-8,r.top-8,r.right+8,r.bottom+8)).save(folder/'selection-button.png')
            expected=button.snapshot['prefix']+translated+button.snapshot['suffix']
            click();tick(lambda:app.inline_input.current is None)
            check(value(field)==expected,'只替换选区并保留两侧 '+field)
            check(page.evaluate('id=>window.state[id]',field)==expected,'编辑器草稿同步 '+field)
            check(page.evaluate('document.activeElement.id')==field and u.GetForegroundWindow()==hwnd,'点击后焦点仍在原输入框 '+field)
            check(calls[-1][1]==selection,'只翻译选中文字 '+field)
            if text.startswith('重复'):
                check(value(field)=='重复｜小一点｜smaller｜后文','重复句子只替换用户选中的第二处')
            tick(lambda:not button.popup.visible)
        check('floating island' in calls[0][0] and 'looks large' in calls[0][0],'带入两侧上下文')
        check(len(app.t.memory('toPeer'))==4,'成功替换只记忆一次')
        memory=len(app.t.memory('toPeer'))
        gate.clear();count=len(calls);select('plain','前｜旧稿｜后','旧稿');click();tick(lambda:len(calls)>count)
        page.evaluate("document.querySelector('#plain').value='用户新稿'")
        gate.set();tick(lambda:app.inline_input.current is None)
        check(value('plain')=='用户新稿' and len(app.t.memory('toPeer'))==memory,'翻译期间改稿不覆盖、不记忆')
        gate.clear();count=len(calls);select('rich','前｜改变选区｜后','改变选区');click();tick(lambda:len(calls)>count)
        page.evaluate("getSelection().collapseToEnd()")
        gate.set();tick(lambda:app.inline_input.current is None)
        check(value('rich')=='前｜改变选区｜后' and len(app.t.memory('toPeer'))==memory,'选区改变后不回填')
        gate.clear();count=len(calls);select('rich','前｜切换输入框｜后','切换输入框');click();tick(lambda:len(calls)>count)
        page.evaluate("document.querySelector('#other').focus()")
        gate.set();tick(lambda:app.inline_input.current is None)
        check(value('rich')=='前｜切换输入框｜后' and value('other')=='' and len(app.t.memory('toPeer'))==memory,'切换输入框不会误写或记忆')
        select('plain','选中后再取消选区','取消选区')
        page.evaluate("const e=document.querySelector('#plain');e.setSelectionRange(0,0)")
        tick(lambda:not button.popup.visible)
        check(not button.popup.visible,'取消选区后按钮收起')
        page.evaluate("const e=document.querySelector('#readonly');e.focus();e.setSelectionRange(0,10)")
        tick(lambda:button.popup.visible and button.snapshot and button.snapshot.get('purpose')=='reference')
        check(button.popup.label.cget('text')=='参考这句','只读区域提供参考入口而非替换')
        page.evaluate("const e=document.querySelector('#password');e.focus();e.value='local-fixture';e.setSelectionRange(0,13)")
        end=time.monotonic()+.7;tick(lambda:time.monotonic()>=end)
        check(not button.popup.visible,'密码输入框不显示按钮')
        check(u.GetClipboardSequenceNumber()==clip,'剪贴板不变')
        check(page.evaluate('window.enters')==0,'未发送Enter')
        check(not callbacks,'无Tk回调异常')
        process=button.process
        app.t.config['selectionButton']=False;app.apply_selection_button()
        tick(lambda:process.poll() is not None)
        check(app.selection_button is None,'关闭选区按钮设置会停止后台识别')
        browser.close()
except Exception as exc:error=str(exc)
finally:
    gate.set();app.on_close()
    result=dict(ok=error is None,passed=passed,error=error,real_user_data_unchanged=before==hashes())
    (folder/'selection-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if error or before!=hashes():sys.exit(1)
