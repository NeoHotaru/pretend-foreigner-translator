"""Measure actual Windows minimize/restore painting with an isolated app."""
import ctypes, hashlib, json, sys, threading, time
from pathlib import Path
from ctypes import wintypes
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
from PIL import ImageGrab
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes()
out=ROOT/'artifacts/window-restore';out.mkdir(parents=True,exist_ok=True)
C.use_sandbox_config(str(out/'pft_sandbox_restore'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,
    asrWarmup=False,globalHotkeys=False,selectionButton=False))
s=C.new_session('窗口恢复测试')
for side in ('toPeer','fromPeer'):
    s[side]=[dict(src='这是本地测试的消息。'*20,out='A local test message. '*20,srcLang='zh',tgtLang='en') for _ in range(20)]
C.save_json(C.SESSION_FILE,{'active':s['name'],'list':[s]})
from translate_app import App
app=App();app.title('NeoHotaru 窗口恢复测试');app.geometry('1240x820+90+70')
errors=[];app.report_callback_exception=lambda *args:errors.append(str(args[1]))
mode='no-transition' if '--no-transition' in sys.argv else 'alpha' if '--alpha' in sys.argv else 'buffered' if '--buffered' in sys.argv else 'optimized' if '--optimized' in sys.argv else 'plain-surfaces' if '--plain-surfaces' in sys.argv else 'filtered' if '--filtered-map' in sys.argv else 'fixed'
if mode=='plain-surfaces':
    from tkinter import ttk
    style=ttk.Style(app)
    for name in ('Lane','TextSurface','TextSurface.Focus','ReadingSurface','ReadingSurface.Focus'):
        style.layout(name+'.TFrame',[('Frame.border',{'sticky':'nsew'})])
if mode=='filtered':
    app.unbind('<Map>')
    app.bind('<Map>',lambda e:app.after(80,app._apply_sash) if e.widget is app else None)
counts={'maps':0,'sash':0};durations=[];original=app._apply_sash
def sash():
    start=time.perf_counter();counts['sash']+=1;original();durations.append(time.perf_counter()-start)
app._apply_sash=sash
def mapped(e):counts['maps']+=1
app.bind('<Map>',mapped,add='+')
u=ctypes.windll.user32
u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
u.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
u.SetForegroundWindow.argtypes=[wintypes.HWND]
u.GetForegroundWindow.restype=wintypes.HWND
u.IsIconic.argtypes=[wintypes.HWND]
pulses=[];last=time.perf_counter();results=[];done=threading.Event()
def pulse():
    global last
    now=time.perf_counter();pulses.append(now-last);last=now
    if not done.is_set():app.after(10,pulse)
def start():
    global expected_sash
    expected_sash=app.paned.winfo_width()//2-25
    app.paned.sashpos(0,expected_sash)
    app.lane_mine.set_input('我还没发送的草稿。')
    hwnd=u.GetAncestor(app.winfo_id(),2)
    if mode=='no-transition':
        dwm=ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        disabled=wintypes.BOOL(True)
        assert dwm.DwmSetWindowAttribute(hwnd,3,ctypes.byref(disabled),ctypes.sizeof(disabled))==0
    if mode=='alpha':app.attributes('-alpha',.999)
    if mode=='buffered':
        get_style=u.GetWindowLongPtrW;get_style.argtypes=[wintypes.HWND,ctypes.c_int];get_style.restype=ctypes.c_ssize_t
        set_style=u.SetWindowLongPtrW;set_style.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t];set_style.restype=ctypes.c_ssize_t
        set_style(hwnd,-20,get_style(hwnd,-20)|0x02000000)
    bounds=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())
    def worker():
        for i in range(3):
            u.ShowWindowAsync(hwnd,6);time.sleep(.6)
            counts['maps']=counts['sash']=0;durations.clear();pulses.clear()
            t=time.perf_counter();u.ShowWindowAsync(hwnd,9);u.SetForegroundWindow(hwnd)
            shots=[]
            for delay in (.02,.08,.2,.5,1.,2.):
                remain=t+delay-time.perf_counter()
                if remain>0:time.sleep(remain)
                if not u.IsIconic(hwnd) and u.GetForegroundWindow()==hwnd:
                    im=ImageGrab.grab(bbox=bounds)
                    # A full-black widget is a painting failure, not dark text.
                    black=sum(1 for r,g,b in im.resize((124,82)).get_flattened_data() if r<8 and g<8 and b<8)
                    shots.append({'time':round(time.perf_counter()-t,3),'black_fraction':round(black/(124*82),4)})
                    if i==0:im.save(out/('%s-%dms.png'%(mode,round(delay*1000))))
            results.append(dict(counts,frames=shots,max_pulse_ms=round(max(pulses,default=0)*1000,2),
                                sash_ms=round(sum(durations)*1000,2)))
        done.set()
    threading.Thread(target=worker,daemon=True).start()
def finish():
    if done.is_set():
        if mode in ('fixed','optimized'):
            assert app.paned.sashpos(0)==expected_sash,'Restore changed the divider'
            assert app.lane_mine.get_input()=='我还没发送的草稿。','Restore changed the draft'
        app.on_close()
    else:app.after(50,finish)
app.after(10,pulse);app.after(1000,start);app.after(100,finish)
app.mainloop()
assert before==hashes(),'Real config changed'
report=dict(mode=mode,cycles=results,errors=errors,real_user_data_unchanged=True)
(out/(mode+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
assert not errors,errors
if mode in ('fixed','optimized'):
    assert all(c['sash']==0 for c in results),'Restore scheduled redundant divider layouts'
    assert all(c['max_pulse_ms']<400 for c in results),'UI stalled during restore'
    assert all(frame['black_fraction']<.01 for c in results for frame in c['frames'] if frame['time']>=.5),'Persistent black widgets after restore'
