"""真实 Tk 主循环中的悬浮岛交互回归，隔离配置与网络。"""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'src'), str(root / 'artifacts' / 'ui-refresh')]
import translator_core as C

def user_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(C.default_user_data_dir()).glob('pretend_foreigner.*.json')}
original_data = user_hashes()
C.use_sandbox_config(str(Path(tempfile.gettempdir()) / 'pft_sandbox_island'))
assert C.is_sandboxed()
C.save_json(C.CONFIG_FILE, dict(C.DEFAULT_CONFIG, setupDone=True, activeBackend='google',
                               globalHotkeys=False, asrWarmup=False, checkUpdates=False))
import translate_app as UI
from island_window import PILL_SIZE, PANEL_SIZE
from overlay import OverlayPanel
from window_capture import window_image

app = UI.App()
app.title('悬浮岛回归沙箱')
app.withdraw()
app.overlay = island = OverlayPanel(app)
island.reduce_motion = False
island._anchor = [600.0, 120.0]
passed, errors, callbacks = [], [], []
app.report_callback_exception = lambda *args: callbacks.append(str(args[1]))
try:
    original_clipboard = app.clipboard_get()
except UI.tk.TclError:
    original_clipboard = None

def check(condition, name):
    (passed if condition else errors).append(name)

def later(delay, function):
    def run():
        try:
            function()
        except Exception as error:
            errors.append('%s: %s' % (function.__name__, error))
            finish()
    app.after(delay, run)

def default_state():
    check((island.winfo_width(), island.winfo_height()) == PILL_SIZE, '默认小胶囊')
    check(not island.expanded and island._pill.winfo_ismapped() and not island._panel.winfo_ismapped(),
          '未点击时只显示胶囊')
    screenshot = window_image(island)
    check(screenshot.getpixel((0, 0))[3] == 0 and screenshot.getpixel((100, 25))[3] == 255,
          '圆角之外真正透明，胶囊内部可见')
    check(len(screenshot.getcolors(PILL_SIZE[0]*PILL_SIZE[1])) > 10, '主界面隐藏时胶囊仍绘制文字与图标')
    island.set_input('原稿第一行\n原稿第二行')
    island.set_output('A saved translation.')
    island.expand()
    later(90, reverse_close)

def reverse_close():
    check(island._morph_id is not None and PILL_SIZE[0] < island.winfo_width() < PANEL_SIZE[0],
          '鼠标展开有中间帧')
    before = island._values[:]
    island.collapse()
    check(max(abs(a-b) for a,b in zip(before,island._values)) < 12, '反向收起从当前展示位置继续')
    later(100, reverse_open)

def reverse_open():
    before = island._values[:]
    island.expand()
    check(max(abs(a-b) for a,b in zip(before,island._values)) < 12, '再展开不中断跳回起点')
    later(650, expanded_state)

def expanded_state():
    check(island._morph_id is None and island.expanded and island._panel.winfo_ismapped(), '动画稳定后显示翻译面板')
    check((island.winfo_width(), island.winfo_height()) == PANEL_SIZE, '展开面板尺寸正确')
    check(island.txt_in.winfo_height() >= 85 and island.txt_out.winfo_height() >= 85, '输入与译文都有可读空间')
    check(island.get_input() == '原稿第一行\n原稿第二行' and island.get_output() == 'A saved translation.',
          '连续开合保留草稿和译文')
    check(app.focus_get() is island.txt_in, '点击展开后焦点进入输入区')
    island.collapse(animate=False)
    start = (island.winfo_x()+40, island.winfo_y()+24)
    island._drag_start(SimpleNamespace(x_root=start[0], y_root=start[1]))
    island._drag_move(SimpleNamespace(x_root=start[0]+45, y_root=start[1]+20))
    island._drag_end(SimpleNamespace(x_root=start[0]+45, y_root=start[1]+20), activates=True)
    check(not island.expanded, '拖动胶囊不被识别为点击展开')
    check(app.t.config.get('overlayIslandPos') == list(map(round,island._anchor)), '拖动位置落盘')
    left, top, right, bottom = island._area()
    island._anchor = [right-PILL_SIZE[0]-8, bottom-PILL_SIZE[1]-8]
    island.expand(animate=False)
    later(100, edge_state)

def edge_state():
    left, top, right, bottom = island._area()
    check(island.winfo_x() >= left and island.winfo_y() >= top and
          island.winfo_x()+island.winfo_width() <= right and
          island.winfo_y()+island.winfo_height() <= bottom, '右下角展开仍完整位于工作区')
    island._escape()
    check(not island.expanded and island._morph_id is None, 'Esc 即时收回胶囊')
    check(island.get_input().startswith('原稿第一行'), 'Esc 不清空输入')
    island.reduce_motion = True
    island.expand()
    check(island.expanded and island._morph_id is None, '减少动画时直接切换形态')
    island.reduce_motion = False
    app.recording_target = island
    island.set_recording(True)
    island.collapse(animate=False)
    check(island.pill_status.cget('text') == '录音', '胶囊保留录音状态')
    island._escape()
    check(app.recording_target is None and not island._recording, '录音时 Esc 优先取消录音')
    app.clipboard_clear()
    app.clipboard_append('剪贴板里的原文')
    def fake_google(text, target, **kwargs):
        time.sleep(.1)
        return dict(text='Clipboard translated locally.', source='zh', target=target)
    C.call_google_free = fake_google
    island.hide()
    app.overlay_clipboard()
    check(island.expanded and island._morph_id is None, '剪贴板快捷键即时展开')
    check(island.get_input() == '剪贴板里的原文', '剪贴板快捷键填入原文')
    island.collapse(animate=False)
    check(island.pill_status.cget('text') == '翻译中', '收起后可继续后台翻译')
    later(400, translated)

def translated():
    check(app.busy == 0 and island.get_output() == 'Clipboard translated locally.', '胶囊模式收到翻译结果')
    check(app.clipboard_get() == 'Clipboard translated locally.', '后台结果自动复制')
    check(island.pill_status.cget('text') == '已复制', '胶囊反馈已复制')
    island.expand(animate=False)
    island.flash('测试反馈')
    island.focus_force()
    # 向主窗口移焦，走真实 FocusOut；随后验证自动收起。
    app.deiconify()
    app.lane_mine.txt_in.focus_force()
    later(750, outside_click)

def outside_click():
    check(not island.expanded, '点击面板之外自动收起')
    check(island.get_output() == 'Clipboard translated locally.', '外部点击保留译文')
    check(not callbacks, '开合/录音/翻译回调无异常')
    finish()

finished = False
def finish():
    global finished
    if finished:
        return
    finished = True
    island.destroy()
    app.overlay = None
    check(all(getattr(island,n) is None for n in ('_morph_id','_focus_id','_region_id','_flash_id')),
          '销毁时取消所有悬浮岛定时器')
    app.clipboard_clear()
    if original_clipboard is not None:
        app.clipboard_append(original_clipboard)
    app.on_close()
    check(original_data == user_hashes(), '真实用户配置与会话未改变')
    print(json.dumps(dict(passed=len(passed), failures=errors, checks=passed), ensure_ascii=False))

island.show()
later(200, default_state)
later(12000, lambda: (check(False, '交互测试超时'), finish()))
app.mainloop()
sys.exit(bool(errors))
