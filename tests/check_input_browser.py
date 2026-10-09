"""Native insertion into an isolated Chrome page; no account or network used."""
import ctypes
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
# Reuse the machine's existing browser QA tools, outside the shipped app.
sys.path.append('D:/Aconnada/Lib/site-packages')
from playwright.sync_api import sync_playwright
from PIL import ImageGrab
import translator_core as C
C.use_sandbox_config(str(ROOT/'artifacts/input-preview/pft_sandbox_browser'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,
    asrWarmup=False,globalHotkeys=False,activeBackend='provider:fixture',providers=[
    dict(name='fixture',apiKey='local-test-fixture',baseUrl='http://example.invalid',model='fixture')]))
C.save_json(C.SESSION_FILE,{'active':'输入演示','list':[C.new_session('输入演示')]})
from translate_app import App
from input_target import capture_target, user32, TargetError
app=App();app.withdraw();app.open_input_composer();panel=app.input_composer;panel.cancel()
callbacks=[];app.report_callback_exception=lambda *a:callbacks.append(str(a[1]))
u=user32();clip=u.GetClipboardSequenceNumber()
passed=[];error=None

def tick(predicate,seconds=4):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.update();panel.pump()
        if predicate():return
        time.sleep(.015)
    raise AssertionError('Timed out: '+panel.lbl_status.cget('text'))

def settle():
    end=time.monotonic()+.3;tick(lambda:time.monotonic()>=end)

HTML='''<!doctype html><meta charset="utf-8"><title>NeoHotaru 隔离浏览器测试</title>
<style>body{font:20px sans-serif;padding:25px}textarea,[contenteditable]{display:block;
width:90%;height:100px;border:1px solid #777;margin:20px 0;padding:12px}</style>
<h2>本地测试页 · 不发送任何消息</h2><textarea id="plain"></textarea>
<div id="rich" contenteditable="true"></div><input id="other">
<script>window.enters=0;document.addEventListener('keydown',e=>{
if(e.key==='Enter'){window.enters++;e.preventDefault()}})</script>'''

try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
                                  args=['--window-position=760,70','--window-size=850,700'])
        page=browser.new_page(viewport={'width':800,'height':570})
        page.set_content(HTML)
        for field,translation in [('plain','make it smaller lol'),('rich','sounds good 😄'),
                                  ('plain','first line\nsecond line 😄')]:
            page.bring_to_front()
            page.evaluate('''id=>{const e=document.getElementById(id);e.focus();
                if(e.tagName==='TEXTAREA'){e.value='keep|replace';e.setSelectionRange(5,12)}
                else{e.textContent='keep|replace';const r=document.createRange();
                r.setStart(e.firstChild,5);r.setEnd(e.firstChild,12);
                const s=getSelection();s.removeAllRanges();s.addRange(r)}}''',field)
            targets=[]
            def captured():
                try:target=capture_target()
                except TargetError:return False
                if 'NeoHotaru 隔离浏览器测试' in target.title:
                    targets.append(target);return True
                return False
            tick(captured)
            panel.show(targets[0]);settle()
            panel.txt_in.delete('1.0','end');panel.txt_in.insert('1.0','那个再小一点，哈哈。')
            app.update()
            with patch.object(C.Translator,'_runner',return_value=lambda *args:json.dumps(
                    dict(text=translation,source='zh',target='en',mode='casual'))):
                panel.request_preview();tick(lambda:not panel.busy)
            assert panel.draft.result
            if field=='plain' and '\n' not in translation:
                panel.update_idletasks()
                rect=ctypes.wintypes.RECT()
                u.GetWindowRect.argtypes=[ctypes.wintypes.HWND,ctypes.POINTER(ctypes.wintypes.RECT)]
                hwnd=u.GetAncestor(panel.winfo_id(),2);u.GetWindowRect(hwnd,ctypes.byref(rect))
                ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom)).save(
                    ROOT/'artifacts/input-preview/composer-preview.png')
            panel.confirm_insert();tick(lambda:not panel.inserting);settle()
            value=page.evaluate('id=>{const e=document.getElementById(id);return e.value??e.innerText}',field)
            if '\n' in translation:
                assert value=='keep|replace',repr(value)
                assert panel.draft.result and '手动粘贴' in panel.lbl_status.cget('text')
                passed.append('multiline: explicit copy fallback, no insertion')
                panel.cancel()
            else:
                assert value=='keep|'+translation,repr((field,value,panel.lbl_status.cget('text')))
                passed.append(field+': '+repr(translation))
            assert page.evaluate('window.enters')==0,'Unexpected Enter/send event'
        assert u.GetClipboardSequenceNumber()==clip,'Clipboard changed'
        assert not callbacks,callbacks
        assert len(app.t.memory('toPeer'))==2
        browser.close()
except Exception as exc:
    error=str(exc)
finally:
    app.on_close()
    result=dict(ok=error is None,passed=passed,error=error,callbacks=callbacks)
    (ROOT/'artifacts/input-preview/browser-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if error:sys.exit(1)
