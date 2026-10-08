"""录制真实 Tk 悬浮岛开合帧；不模拟界面，不调用网络。"""
import base64
import io
import json
import sys
import time
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'src'), str(root / 'artifacts' / 'ui-refresh')]
import translator_core as C
C.use_sandbox_config()
assert C.is_sandboxed()
C.save_json(C.CONFIG_FILE, dict(C.DEFAULT_CONFIG, setupDone=True, activeBackend='google',
                               globalHotkeys=False, asrWarmup=False, checkUpdates=False))
import translate_app as UI
from overlay import OverlayPanel
from island_window import PANEL_SIZE, PILL_SIZE
from window_capture import window_image

app = UI.App()
app.title('悬浮岛动画沙箱预览')
app.withdraw()
app.overlay = island = OverlayPanel(app)
island.reduce_motion = False
island._anchor = [700.0, 100.0]
frames, durations = [], []
left = 700 + (PILL_SIZE[0] - PANEL_SIZE[0]) // 2
stage_started = 0.0
stage = 0

def frame(duration=40):
    app.update_idletasks()
    screenshot = window_image(island)
    canvas = Image.new('RGBA', PANEL_SIZE, (0,0,0,0))
    canvas.alpha_composite(screenshot, (island.winfo_x()-left, island.winfo_y()-100))
    frames.append(canvas)
    durations.append(duration)

def begin():
    global stage_started
    app.t.rename_session(app.t.active, '前端重构')
    island.refresh_memory()
    island.set_input('点开小岛，就能继续说话。')
    island.set_output('Open the island and keep the conversation going.')
    island.show()
    app.after(200, open_island)

def open_island():
    global stage_started
    frame(800)
    island.expand(focus=False)
    stage_started = time.perf_counter()
    app.after(35, record)

def record():
    global stage, stage_started
    frame()
    if time.perf_counter() - stage_started < .65:
        app.after(35, record)
    elif stage == 0:
        durations[-1] = 1300
        stage = 1
        app.after(300, close_island)
    else:
        durations[-1] = 900
        finish()

def close_island():
    global stage_started
    island.collapse()
    stage_started = time.perf_counter()
    app.after(35, record)

def finish():
    try:
        out = io.BytesIO()
        frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:],
                       duration=durations, loop=0, disposal=2)
        print(json.dumps(dict(image=base64.b64encode(out.getvalue()).decode(), frames=len(frames))))
    finally:
        app.on_close()

app.after(400, begin)
app.mainloop()
