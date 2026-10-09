"""Packaged inline translator: local fake API and independent browser editor."""
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
from playwright.sync_api import sync_playwright
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes()
base=ROOT/'artifacts/input-preview/pft_sandbox_exe'
C.use_sandbox_config(str(base/'pretend-foreigner'))
calls=[]
PEER='Maya can make the floating island smaller tomorrow.'
ZH='Maya 明天可以把悬浮窗缩小。'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        peer=calls[-1]['messages'][-1]['content']==PEER
        result=dict(text=ZH,source='en',target='zh',mode='precise') if peer else dict(text='make the floating island smaller lol',source='zh',target='en',mode='casual')
        body=json.dumps({'choices':[{'message':{'content':json.dumps(result)}}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,windowGeometry='1240x860+80+60',setupDone=True,checkUpdates=False,asrWarmup=False,globalHotkeys=True,hotkeyToggle=[9,0x78],hotkeyClipboard=[9,0x79],activeBackend='provider:fixture',providers=[dict(name='fixture',apiKey='local-test-fixture',baseUrl='http://127.0.0.1:%d'%server.server_port,model='fixture')]))
session=C.new_session('打包试用检查')
session['toPeer']=[dict(src='悬浮窗',out='floating island',srcLang='zh',tgtLang='en')]
session['fromPeer']=[dict(src='The floating island looks large.',out='悬浮窗有点大。',srcLang='en',tgtLang='zh')]
C.save_json(C.SESSION_FILE,{'active':session['name'],'list':[session]})
from input_target import capture_target,user32,TargetError
u=user32();clip=u.GetClipboardSequenceNumber()
exe_path=Path(sys.argv[sys.argv.index('--exe')+1]) if '--exe' in sys.argv else ROOT/'dist/input-preview/pretend-foreigner/pretend-foreigner.exe'
app=subprocess.Popen([str(exe_path)],env=dict(os.environ,APPDATA=str(base)))
def wait(predicate,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.04)
    raise AssertionError('Packaged inline test timed out')
u.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];u.FindWindowW.restype=wintypes.HWND
u.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
passed=[];error=None;main=None
HTML='''<!doctype html><meta charset="utf-8"><title>NeoHotaru 打包原位测试</title>
<style>body{font:20px sans-serif;padding:30px;background:#f5f5f7}#draft{padding:20px;height:150px;border:1px solid #aaa;border-radius:12px;background:white;margin-top:30px}</style>
<h2>选区翻译测试</h2><p>选中文字，点击旁边的「假装翻译」，只替换选中部分。</p>
<p id="peer"></p>
<div id="draft" contenteditable="true" role="textbox" class="ProseMirror"></div>
<script>window.draftState='';window.enters=0;document.addEventListener('input',e=>{window.draftState=e.target.innerText});document.addEventListener('keydown',e=>{if(e.key==='Enter'){window.enters++;e.preventDefault()}})</script>'''
try:
    def main_ready():
        global main
        hwnd=u.FindWindowW(None,C.APP_NAME+'  ·  Pretend Foreigner Translator · 沙箱')
        pid=wintypes.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if hwnd and pid.value==app.pid:main=hwnd;return True
        return False
    wait(main_ready);time.sleep(.8)
    # Repeat the user's minimize -> restore path on the actual packaged app.
    # Only inspect this independently configured process, never another window.
    from PIL import ImageGrab
    (ROOT/'artifacts/window-restore').mkdir(parents=True,exist_ok=True)
    u.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
    u.IsIconic.argtypes=[wintypes.HWND]
    u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    for cycle in range(3):
        u.ShowWindowAsync(main,6);wait(lambda:u.IsIconic(main));time.sleep(.4)
        u.ShowWindowAsync(main,9);u.SetForegroundWindow(main)
        wait(lambda:not u.IsIconic(main) and u.GetForegroundWindow()==main)
        time.sleep(.6)
        if u.GetForegroundWindow()!=main:
            wait(main_ready);u.SetForegroundWindow(main)
            wait(lambda:u.GetForegroundWindow()==main);time.sleep(.2)
        assert u.GetForegroundWindow()==main,'Test window lost foreground before capture'
        rect=wintypes.RECT();u.GetWindowRect(main,ctypes.byref(rect))
        frame=ImageGrab.grab(bbox=(rect.left+10,rect.top+50,rect.right-10,rect.bottom-10))
        pixels=list(frame.resize((120,80)).get_flattened_data())
        black=sum(1 for r,g,b in pixels if r<8 and g<8 and b<8)/len(pixels)
        frame.save(ROOT/('artifacts/window-restore/exe-restore-cycle-%d.png'%cycle))
        assert black<.01,'Packaged restore still has black widgets: %.3f'%black
        if cycle==0:frame.save(ROOT/'artifacts/window-restore/exe-restored.png')
    passed.append('EXE repeated minimize/restore has no persistent black widgets')
    if '--restore-only' in sys.argv:
        assert before==hashes(),'Real user data changed'
        print(json.dumps(dict(ok=True,passed=passed,real_user_data_unchanged=True)))
        raise SystemExit(0)  # finally still closes only this isolated test app.
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',args=['--window-position=760,70','--window-size=850,700','--force-renderer-accessibility'])
        page=browser.new_page(viewport={'width':800,'height':570});page.set_content(HTML);page.bring_to_front()
        wait(lambda:u.FindWindowW(None,'NeoHotaru 打包原位测试 - Google Chrome'))
        hwnd=u.FindWindowW(None,'NeoHotaru 打包原位测试 - Google Chrome')
        u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        rect=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect));x,y=rect.left+80,rect.top+15
        u.WindowFromPoint.argtypes=[wintypes.POINT];u.WindowFromPoint.restype=wintypes.HWND
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==hwnd
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        page.evaluate('''text=>{const draft=document.querySelector('#draft');draft.focus();draft.textContent='未发送的草稿';
            const peer=document.querySelector('#peer');peer.textContent=text;const r=document.createRange();r.selectNodeContents(peer);
            const s=getSelection();s.removeAllRanges();s.addRange(r)}''',PEER)
        def popup_visible():
            h=u.FindWindowW(None,'假装翻译 · 选区按钮');return h and u.IsWindowVisible(h)
        wait(popup_visible)
        popup=u.FindWindowW(None,'假装翻译 · 选区按钮');r=wintypes.RECT();u.GetWindowRect(popup,ctypes.byref(r))
        x,y=(r.left+r.right)//2,(r.top+r.bottom)//2
        wait(lambda:u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==popup)
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        wait(lambda:len(C.load_json(C.SESSION_FILE,{}).get('list',[{}])[0].get('fromPeer',[]))==2)
        wait(lambda:C.load_json(C.SESSION_FILE,{})['list'][0]['fromPeer'][-1]['out']==ZH)
        bubble=u.FindWindowW(None,'假装翻译 · 对方消息译文')
        assert bubble and u.IsWindowVisible(bubble)
        assert page.evaluate("document.querySelector('#peer').innerText")==PEER
        assert page.evaluate("document.querySelector('#draft').innerText")=='未发送的草稿'
        assert u.GetForegroundWindow()==hwnd
        passed.append('EXE readonly reference records peer original + Chinese translation and opens reading bubble')
        u.GetWindowRect(bubble,ctypes.byref(r));x,y=r.right-30,r.top+28
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==bubble
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        wait(lambda:not u.IsWindowVisible(bubble))
        page.evaluate("const e=document.querySelector('#draft');e.focus();e.textContent='保留前文｜那个悬浮窗再小一点，哈哈。｜保留后文';const r=document.createRange();r.setStart(e.firstChild,5);r.setEnd(e.firstChild,e.textContent.length-5);const s=getSelection();s.removeAllRanges();s.addRange(r)")
        def target_ready():
            try:target=capture_target()
            except TargetError:return False
            return 'NeoHotaru 打包原位测试' in target.title
        wait(target_ready)
        def selection_button_visible():
            hwnd=u.FindWindowW(None,'假装翻译 · 选区按钮')
            return hwnd and u.IsWindowVisible(hwnd)
        wait(selection_button_visible)
        popup=u.FindWindowW(None,'假装翻译 · 选区按钮')
        button_rect=wintypes.RECT();u.GetWindowRect(popup,ctypes.byref(button_rect))
        x,y=(button_rect.left+button_rect.right)//2,(button_rect.top+button_rect.bottom)//2
        wait(lambda:u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==popup)
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        wait(lambda:len(calls)==2)
        assert len(C.load_json(C.SESSION_FILE,{})['list'][0]['toPeer'])==1
        prompt=calls[-1]['messages'][0]['content']
        assert 'floating island' in prompt and 'looks large' in prompt and PEER in prompt
        assert calls[-1]['messages'][-1]['content']=='那个悬浮窗再小一点，哈哈。'
        passed.append('EXE mouse selection button uses only selected Chinese and both memories')
        expected='保留前文｜make the floating island smaller lol｜保留后文'
        wait(lambda:page.evaluate('window.draftState')==expected)
        assert page.evaluate("document.querySelector('#draft').innerText")==expected
        assert page.evaluate('document.activeElement.id')=='draft'
        assert page.evaluate('window.enters')==0
        wait(lambda:len(C.load_json(C.SESSION_FILE,{}).get('list',[{}])[0].get('toPeer',[]))==2)
        assert u.GetClipboardSequenceNumber()==clip
        assert not u.FindWindowW(None,'假装外国人 · 翻译输入')
        passed.append('EXE replaces selection, preserves both sides and focus, no send or composer')
        # Open the new reference-details entry after the actual inline result.
        wait(main_ready);u.ShowWindowAsync(main,9)
        # Windows foreground locking rejects SetForegroundWindow after typing
        # in Chrome. Activate the verified test title bar as a person would.
        main_rect=wintypes.RECT();u.GetWindowRect(main,ctypes.byref(main_rect))
        x,y=main_rect.left+100,main_rect.top+15
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==main
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        wait(lambda:u.GetForegroundWindow()==main);time.sleep(.4)
        main_rect=wintypes.RECT();u.GetWindowRect(main,ctypes.byref(main_rect))
        ImageGrab.grab(bbox=(main_rect.left+8,main_rect.top+32,main_rect.right-8,main_rect.bottom-8)).save(ROOT/'artifacts/context-probes/main-exe.png')
        x,y=main_rect.left+350,main_rect.bottom-95
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==main
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        wait(lambda:u.FindWindowW(None,'翻译时带入的上下文'))
        context=u.FindWindowW(None,'翻译时带入的上下文')
        owner_pid=wintypes.DWORD();u.GetWindowThreadProcessId(context,ctypes.byref(owner_pid))
        assert owner_pid.value==app.pid
        context_rect=wintypes.RECT();u.GetWindowRect(context,ctypes.byref(context_rect))
        time.sleep(.3)
        (ROOT/'artifacts/context-probes').mkdir(exist_ok=True,parents=True)
        ImageGrab.grab(bbox=(context_rect.left+8,context_rect.top+32,context_rect.right-8,context_rect.bottom-8)).save(ROOT/'artifacts/context-probes/context-exe.png')
        passed.append('EXE inline translation opens actual context details')
        u.PostMessageW(context,0x0010,0,0)
        page.screenshot(path=str(ROOT/'artifacts/input-preview/inline-exe-preview.png'))
        browser.close()
except Exception as exc:error=str(exc)
finally:
    if main:u.PostMessageW(main,0x0010,0,0)
    try:app.wait(timeout=5)
    except subprocess.TimeoutExpired:app.terminate();app.wait(timeout=3)
    server.shutdown();server.server_close()
    result=dict(ok=error is None,passed=passed,error=error,real_user_data_unchanged=before==hashes())
    (ROOT/'artifacts/input-preview/exe-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if error or before!=hashes():sys.exit(1)
