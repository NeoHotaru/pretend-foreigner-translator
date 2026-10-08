"""沙箱预览；stdout 传递截图，PowerShell 写文件，不接触用户配置。"""
import base64
import ctypes
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import translator_core as C
C.use_sandbox_config()
assert C.is_sandboxed()
config = dict(C.DEFAULT_CONFIG, setupDone=True, activeBackend='google',
              globalHotkeys=False, asrWarmup=False, checkUpdates=False)
config['windowGeometry'] = '1280x860+30+30'
C.save_json(C.CONFIG_FILE, config)
import translate_app as UI
from PIL import Image

app = UI.App()
app.title('假装外国人 · 界面沙箱预览')
mode = sys.argv[1] if len(sys.argv) > 1 else 'main'

def capture():
    app.t.rename_session(app.t.active, '前端重构')
    app.load_session_into_ui()
    app.v_note.set('悬浮窗 = floating panel')
    app.lane_mine.set_input('我们先把主界面理顺，再改悬浮窗。\n\n字号大一点，复制按钮放在译文旁边，记忆列表需要时再展开。')
    app.lane_mine.set_output("Let's get the main window right first, then work on the floating panel.\n\nUse slightly larger text, put the copy button next to the translation, and let me open the history when I need it.")
    app.lane_peer.set_input('That makes sense. Keep the most frequent actions within easy reach, and give the translation enough room to breathe.')
    app.lane_peer.set_output('可以。把常用操作放在顺手的位置，也给译文留出足够的阅读空间。')
    app.t.current_session()['toPeer'] = [dict(src='字号大一点', out='Use slightly larger text.'),
                                          dict(src='复制按钮放在译文旁边', out='Put the copy button next to the translation.')]
    app.sync_views()
    app.status('翻译完成，译文已自动复制', 'ok')
    target = app
    if mode == 'expanded':
        app.lane_mine.toggle_memory()
        app.lane_peer.toggle_memory()
    if mode == 'small':
        app.geometry('1120x740+30+30')
    if mode == 'memory':
        app.lane_mine.toggle_memory()
        target = app.lane_mine.memory_window
    if mode == 'settings':
        target = UI.SettingsDialog(app)
    if mode == 'setup':
        from setup_wizard import SetupWizard
        target = SetupWizard(app)
    if mode == 'overlay':
        from overlay import OverlayPanel
        app.overlay = target = OverlayPanel(app)
        target.geometry('+80+80')
        target.deiconify()
        target.set_input('我们先把主界面理顺，再改悬浮窗。')
        target.set_output("Let's get the main window right first, then work on the floating panel.")
    app.after(400, lambda: finish(target))

def window_image(target):
    """PrintWindow 只截本窗口，避免其他应用遮挡或混入画面。"""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    for fun in (u.GetDC, u.GetAncestor, g.CreateCompatibleDC,
                g.CreateCompatibleBitmap, g.SelectObject):
        fun.restype = ctypes.c_void_p
    u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    g.DeleteObject.argtypes = [ctypes.c_void_p]
    g.DeleteDC.argtypes = [ctypes.c_void_p]
    u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    w, h = target.winfo_width(), target.winfo_height()
    hwnd = u.GetAncestor(target.winfo_id(), 2)
    screen = u.GetDC(None)
    dc = g.CreateCompatibleDC(screen)
    bitmap = g.CreateCompatibleBitmap(screen, w, h)
    old = g.SelectObject(dc, bitmap)
    try:
        assert u.PrintWindow(hwnd, dc, 1)
        import struct
        info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0))
        data = ctypes.create_string_buffer(w*h*4)
        assert g.GetDIBits(dc, bitmap, 0, h, data, info, 0)
        return Image.frombytes('RGB', (w, h), data.raw, 'raw', 'BGRX')
    finally:
        g.SelectObject(dc, old)
        g.DeleteObject(bitmap)
        g.DeleteDC(dc)
        u.ReleaseDC(None, screen)

def finish(target):
    try:
        app.update_idletasks()
        w, h = target.winfo_width(), target.winfo_height()
        im = window_image(target)
        out = io.BytesIO()
        im.save(out, format='PNG')
        print(json.dumps(dict(image=base64.b64encode(out.getvalue()).decode(), width=w, height=h)))
    finally:
        app.on_close()

app.after(500, capture)
app.mainloop()
