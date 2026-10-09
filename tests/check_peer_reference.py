"""Readonly received message -> reference memory + Chinese bubble -> reply."""
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
before=hashes();folder=ROOT/'artifacts/input-preview'
C.use_sandbox_config(str(folder/'pft_sandbox_peer_reference'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,asrWarmup=False,
    globalHotkeys=False,selectionButton=True,activeBackend='provider:fixture',providers=[
    dict(name='fixture',apiKey='local-test-fixture',baseUrl='http://example.invalid',model='fixture')]))
session=C.new_session('参考消息测试')
session['toPeer']=[dict(src='再小一点',out='a little smaller',srcLang='zh',tgtLang='en')]
C.save_json(C.SESSION_FILE,{'active':session['name'],'list':[session]})
from translate_app import App
from input_target import user32
app=App();app.withdraw();callbacks=[]
app.report_callback_exception=lambda *args:callbacks.append(str(args[1]))
u=user32();clip=u.GetClipboardSequenceNumber();gate=threading.Event();gate.set()
calls=[];fail_next=False;passed=[];error=None
PEER='Maya can make the floating island smaller tomorrow.'
ZH='Maya 明天可以把悬浮窗缩小。'
PEER2='Use the blue version instead.'
def runner(key):
    def translate(prompt,text):
        global fail_next
        calls.append((prompt,text));gate.wait(10)
        if fail_next:
            fail_next=False;raise RuntimeError('本地测试的翻译失败')
        if text==PEER:return json.dumps(dict(text=ZH,source='en',target='zh',mode='precise'))
        if text==PEER2:return json.dumps(dict(text='改用蓝色那个版本。',source='en',target='zh',mode='precise'))
        if text.startswith('那就让她'):return json.dumps(dict(text='Then let Maya do it tomorrow.',source='zh',target='en',mode='casual'))
        return json.dumps(dict(text='稍后告诉你。',source='en',target='zh',mode='precise'))
    return translate
def tick(predicate,seconds=12,label='completion'):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.update()
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Timeout '+label+': '+app.lbl_status.cget('text')+'; callbacks='+str(callbacks))
def check(value,name):
    assert value,name
    passed.append(name)
HTML='''<!doctype html><meta charset="utf-8"><title>NeoHotaru 对方消息测试</title>
<style>body{font:18px sans-serif;padding:25px}#peer{line-height:1.6;padding:20px;background:#edf0f4}
textarea{display:block;width:85%;height:100px;margin-top:70px;padding:12px;font:18px sans-serif}</style>
<h2>对方消息与回复 · 本地测试</h2><p id="peer"></p><textarea id="reply"></textarea>
<script>window.enters=0;window.draft='';document.addEventListener('input',e=>window.draft=e.target.value);
document.addEventListener('keydown',e=>{if(e.key==='Enter'){window.enters++;e.preventDefault()}})</script>'''
try:
    with sync_playwright() as p,patch.object(C.Translator,'_runner',side_effect=runner):
        browser=p.chromium.launch(headless=False,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
            args=['--window-position=700,70','--window-size=900,850','--force-renderer-accessibility'])
        page=browser.new_page(viewport={'width':850,'height':730});page.set_content(HTML);page.bring_to_front()
        u.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];u.FindWindowW.restype=wintypes.HWND
        u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        u.WindowFromPoint.argtypes=[wintypes.POINT];u.WindowFromPoint.restype=wintypes.HWND
        tick(lambda:u.FindWindowW(None,'NeoHotaru 对方消息测试 - Google Chrome'))
        hwnd=u.FindWindowW(None,'NeoHotaru 对方消息测试 - Google Chrome')
        r=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(r));x,y=r.left+80,r.top+15
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==hwnd
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        tick(lambda:app.selection_button is not None);button=app.selection_button
        def select_peer(text):
            page.evaluate('''text=>{const reply=document.querySelector('#reply');reply.focus();
                const e=document.querySelector('#peer');e.textContent=text;const r=document.createRange();
                r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r)}''',text)
            tick(lambda:button.popup.visible and button.snapshot and button.snapshot['selected']==text,label='readonly selection')
            check(button.snapshot['purpose']=='reference' and button.popup.label.cget('text')=='参考这句','只读消息显示参考这句')
        def click_popup():
            root=u.GetAncestor(button.popup.winfo_id(),2);r=wintypes.RECT();u.GetWindowRect(root,ctypes.byref(r))
            x,y=(r.left+r.right)//2,(r.top+r.bottom)//2
            assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==root
            u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
            tick(lambda:app.peer_reference is not None and app.peer_reference.current is not None)
        page.evaluate("document.querySelector('#reply').value='我还没发的草稿'")
        gate.clear();select_peer(PEER);click_popup();peer=app.peer_reference
        tick(lambda:len(calls)==1)
        check(len(app.t.memory('fromPeer'))==1 and app.t.memory('fromPeer')[0]['src']==PEER,
              '点击后原话立即进入对方上下文')
        check(app.t.memory('fromPeer')[0]['out']=='' and len(app.t.memory('toPeer'))==1,'等待译文时不污染自己的记忆')
        check(peer.bubble.visible and u.GetForegroundWindow()==hwnd,'翻译气泡不抢聊天窗口焦点')
        gate.set();tick(lambda:not peer.current.pending)
        check(peer.bubble.output.get('1.0','end-1c')==ZH,'气泡显示对方消息的中文译文')
        check(app.t.memory('fromPeer')[0]['out']==ZH and len(app.t.memory('fromPeer'))==1,'原文译文在同一条对方记录中')
        check(page.evaluate("document.querySelector('#peer').innerText")==PEER and
              page.evaluate("document.querySelector('#reply').value")=='我还没发的草稿','对方原消息与未发草稿保持不变')
        root=u.GetAncestor(peer.bubble.winfo_id(),2);r=wintypes.RECT();u.GetWindowRect(root,ctypes.byref(r))
        ImageGrab.grab(bbox=(r.left,r.top,r.right,r.bottom)).save(folder/'peer-reference-bubble.png')
        peer.cancel()
        page.evaluate("const e=document.querySelector('#reply');e.focus();e.value='那就让她明天改吧。';e.setSelectionRange(0,e.value.length)")
        tick(lambda:button.popup.visible and button.snapshot and button.snapshot.get('purpose')=='translate')
        root=u.GetAncestor(button.popup.winfo_id(),2);r=wintypes.RECT();u.GetWindowRect(root,ctypes.byref(r))
        x,y=(r.left+r.right)//2,(r.top+r.bottom)//2
        hit=u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)
        from input_target import window_text
        tick(lambda:u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x,y)),2)==root,label='reply button ready')
        u.SetCursorPos(x,y);u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
        tick(lambda:app.inline_input is not None and app.inline_input.current is not None)
        tick(lambda:app.inline_input.current is None)
        check(PEER in calls[-1][0] and 'Maya' in calls[-1][0],'随后自己的回复确实带入对方参考消息')
        check(page.evaluate("document.querySelector('#reply').value")=='Then let Maya do it tomorrow.','回复仍可原位翻译')
        fail_next=True;select_peer(PEER2);click_popup();tick(lambda:not peer.current.pending)
        check(len(app.t.memory('fromPeer'))==2 and app.t.memory('fromPeer')[-1]['src']==PEER2,'翻译失败也保留已确认的参考原文')
        check('翻译失败' in peer.bubble.status.cget('text') and bool(peer.bubble.retry.winfo_manager()),'失败气泡提供重试')
        page.evaluate("getSelection().removeAllRanges();document.querySelector('#reply').focus()")
        peer.retry();tick(lambda:not peer.current.pending)
        check(peer.bubble.output.get('1.0','end-1c')=='改用蓝色那个版本。' and len(app.t.memory('fromPeer'))==2,
              '重试读取已确认原文并补齐译文，不重复加入')
        peer.cancel()
        gate.clear();count=len(calls);select_peer('I will tell you later.');click_popup();tick(lambda:len(calls)>count)
        old_session=app.t.current_session();app.t.add_session('另一个会话');app.load_session_into_ui()
        gate.set();tick(lambda:not peer.current.pending)
        check(app.t.memory('fromPeer')==[] and old_session['fromPeer'][-1]['out']=='','换会话不把迟到译文写到新会话')
        peer.cancel();app.t.switch_session('参考消息测试');app.load_session_into_ui()
        gate.clear();count=len(calls);select_peer('I will explain it tomorrow.');click_popup();tick(lambda:len(calls)>count)
        peer.cancel();gate.set();end=time.monotonic()+.3;tick(lambda:time.monotonic()>=end)
        check(not peer.bubble.visible and peer.current is None and app.busy==0,'关闭气泡后迟到结果不复活窗口')
        check(app.t.memory('fromPeer')[-1]['src']=='I will explain it tomorrow.','关闭气泡保留用户已确认的参考原文')
        app.t.config['activeBackend']='google'
        with patch.object(C,'call_google_free',return_value=dict(text=ZH,source='en',target='zh')):
            select_peer(PEER);click_popup();tick(lambda:not peer.current.pending)
        check(peer.bubble.output.get('1.0','end-1c')==ZH and '免费机翻不使用上下文' in peer.bubble.status.cget('text'),
              '免费机翻显示译文并说明不使用上下文')
        peer.cancel();app.t.config['activeBackend']='provider:fixture';app.t.config['crossMemoryDepth']=0
        select_peer(PEER2);click_popup();tick(lambda:not peer.current.pending)
        check('开启参照对方消息' in peer.bubble.status.cget('text') and
              app.t.plan('接下来怎么做？','toPeer')['cross_count']==0,'关闭参照时提示真实设置，不承诺参考生效')
        peer.cancel()
        check(u.GetClipboardSequenceNumber()==clip and page.evaluate('window.enters')==0,'不改剪贴板、不发送消息')
        check(not callbacks,'无Tk回调异常');browser.close()
except Exception as exc:error=str(exc)
finally:
    gate.set();app.on_close()
    result=dict(ok=error is None,passed=passed,error=error,real_user_data_unchanged=before==hashes())
    (folder/'peer-reference-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if error or before!=hashes():sys.exit(1)
