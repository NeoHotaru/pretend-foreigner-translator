import ctypes,json,sys
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
sys.path.insert(0,str(ROOT/'artifacts/ui-refresh'))
from PIL import ImageGrab
from window_capture import window_image
import translator_core as C
out=ROOT/'artifacts/context-probes';out.mkdir(exist_ok=True,parents=True)
C.use_sandbox_config(str(out/'pft_sandbox_float'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,asrWarmup=False,
    globalHotkeys=False,selectionButton=False,activeBackend='provider:fixture',providers=[
        dict(name='fixture',apiKey='fixture',baseUrl='http://example.invalid',model='fixture')]))
from translate_app import App
from overlay import OverlayPanel
app=App();app.withdraw()
s=app.t.current_session();s['fromPeer']=[dict(src='Maya can do it tomorrow.',out='Maya 明天可以处理。')]
usage=app.t.plan('那就明天吧。','toPeer')['context_usage']
app.record_translation_context(dict(lane='toPeer',text='Then tomorrow.',context_usage=usage),s,'那就明天吧。')
app.overlay=panel=OverlayPanel(app);panel.show();app.update();panel.expand(animate=False,focus=True)
panel.set_input('那就明天吧。');panel.set_output('Then tomorrow.')
u=ctypes.windll.user32
u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
u.WindowFromPoint.argtypes=[wintypes.POINT];u.WindowFromPoint.restype=wintypes.HWND
errors=[];app.report_callback_exception=lambda *args:errors.append(str(args[1]))
def capture():
    try:
        x,y=panel.winfo_rootx(),panel.winfo_rooty();w,h=panel.winfo_width(),panel.winfo_height()
        hwnd=u.GetAncestor(panel.winfo_id(),2);rect=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
        assert u.GetAncestor(u.WindowFromPoint(wintypes.POINT(x+w//2,y+h//2)),2)==hwnd
        physical=ImageGrab.grab(bbox=(x+16,y+16,x+w-16,y+h-16),all_screens=True);physical.save(out/'island-physical.png')
        window_image(panel).save(out/'island-print.png')
        black=sum(1 for r,g,b in physical.resize((60,90)).get_flattened_data() if r<8 and g<8 and b<8)/5400
        print(json.dumps(dict(tk=[w,h],xy=[x,y],screen=[panel.winfo_screenwidth(),panel.winfo_screenheight()],
            system=[u.GetSystemMetrics(0),u.GetSystemMetrics(1),u.GetSystemMetrics(76),u.GetSystemMetrics(78)],
            native=[rect.left,rect.top,rect.right,rect.bottom],black=black,errors=errors)))
        assert black<.01,'Floating context UI has black pixels'
        app.open_translation_context('toPeer',owner=panel);app.update()
        app.context_view.btn_settings.invoke();app.update()
        assert app.winfo_viewable() and app.context_dialog.winfo_viewable(),'Context settings sheet was hidden with its parent'
        assert not errors,errors
    finally:app.on_close()
app.after(600,capture);app.mainloop()
assert not errors,errors
