"""真实窗口截图与交互帧预览，只写沙箱配置。"""
import base64
import io
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'src'), str(root / 'artifacts' / 'ui-refresh')]
import translator_core as C
C.use_sandbox_config()
assert C.is_sandboxed()
C.save_json(C.CONFIG_FILE, dict(C.DEFAULT_CONFIG, setupDone=True, activeBackend='google',
                               globalHotkeys=False, asrWarmup=False, checkUpdates=False))
import translate_app as UI
from overlay import OverlayPanel
from window_capture import window_image
app = UI.App()
app.title('悬浮岛沙箱预览')
app.withdraw()
app.overlay = island = OverlayPanel(app)
island._anchor = [700.0, 130.0]
mode = sys.argv[1] if len(sys.argv) > 1 else 'pill'

def prepare():
    app.t.rename_session(app.t.active, '前端重构')
    island.refresh_memory()
    island.set_input('我们先把悬浮窗收成一个小岛。\n点一下，就能继续用自己的语气说话。')
    island.set_output("Let's turn the floating window into a little island.\nOne click, and I can keep talking in my own voice.")
    island.show(expanded=mode != 'pill')
    if mode == 'recording':
        island.collapse(animate=False)
        island.set_recording(True)
    app.after(300, capture)

def capture():
    try:
        app.update_idletasks()
        out = io.BytesIO()
        image = window_image(island)
        image.save(out, format='PNG')
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        u.GetAncestor.restype = ctypes.c_void_p
        hwnd = u.GetAncestor(island.winfo_id(), 2)
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        rect = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        print(json.dumps(dict(width=island.winfo_width(), height=island.winfo_height(),
                             mapped=island.winfo_ismapped(), panel=island._panel.winfo_ismapped(),
                             pill=island._pill.winfo_ismapped(), extrema=image.getextrema(),
                             visible=bool(u.IsWindowVisible(hwnd)), style=u.GetWindowLongW(hwnd,-16),
                             exstyle=u.GetWindowLongW(hwnd,-20), rect=[rect.left,rect.top,rect.right,rect.bottom],
                             image=base64.b64encode(out.getvalue()).decode())))
    finally:
        app.on_close()

app.after(400, prepare)
app.mainloop()
