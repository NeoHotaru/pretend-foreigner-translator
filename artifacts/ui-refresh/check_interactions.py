"""走真实 tkinter 主循环，使用本地假响应验证界面接线，不发网络请求。"""
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import translator_core as C

real_dir = Path(C.default_user_data_dir())
def user_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in real_dir.glob('pretend_foreigner.*.json')}
before = user_hashes()
C.use_sandbox_config(str(Path(C.CONFIG_FILE).parent / 'pft_sandbox_ui_refresh'))
assert C.is_sandboxed()
config = dict(C.DEFAULT_CONFIG, setupDone=True, activeBackend='google', globalHotkeys=False,
              asrWarmup=False, checkUpdates=False, windowGeometry='1120x740')
C.save_json(C.CONFIG_FILE, config)
import translate_app as UI
from overlay import OverlayPanel

app = UI.App()
app.title('界面交互回归（沙箱）')
passed, errors, callbacks = [], [], []
try:
    original_clipboard = app.clipboard_get()
except UI.tk.TclError:
    original_clipboard = None
app.report_callback_exception = lambda *args: callbacks.append(str(args[1]))

def check(condition, label):
    (passed if condition else errors).append(label)

def guarded(function):
    def run():
        try:
            function()
        except Exception as e:
            errors.append('%s: %s' % (function.__name__, e))
            finish()
    return run

def start():
    app.update_idletasks()
    for lane in (app.lane_mine, app.lane_peer):
        check(lane.txt_in.winfo_height() >= 75 and lane.txt_out.winfo_height() >= 75,
              '最小窗口仍能阅读输入和译文 ' + lane.side)
    check(app.lbl_status.winfo_rooty() + app.lbl_status.winfo_height() <=
          app.winfo_rooty() + app.winfo_height(), '状态栏在窗口内')
    app.lane_mine.toggle_memory()
    app.update_idletasks()
    check(app.lane_mine.memory_window.winfo_viewable() and app.lane_mine.txt_in.winfo_height() >= 75,
          '查看记忆不挤掉输入框')
    app.lane_mine.toggle_memory()
    app.open_context_settings()
    app.v_depth.set('5')
    app.context_dialog.event_generate('<Escape>')
    # event_generate 不依赖输入焦点；窗口管理器关闭路径同样保存设置。
    if app.context_dialog.winfo_exists():
        app.context_dialog.tk.call(app.context_dialog.protocol('WM_DELETE_WINDOW'))
    check(app.t.config['memoryDepth'] == 5, '上下文设置保存')
    app.overlay = OverlayPanel(app)
    app.overlay.deiconify()
    app.overlay.set_side('fromPeer')
    check(app.overlay.side == 'fromPeer' and app.overlay.btn_go.cget('style') == 'PeerGo.TButton',
          '悬浮窗切换方向与主操作颜色一致')
    app.overlay.set_recording(True)
    app.overlay.set_level(.6, 1.2, .6)
    check(app.overlay.lvl.winfo_manager() == 'pack' and '60%' in app.overlay.lbl_hint.cget('text'),
          '悬浮窗录音反馈可见')
    app.overlay.set_recording(False)
    app.overlay.set_side('toPeer')
    check(not app.overlay.lvl.winfo_manager(), '停止录音收起电平')
    # 替换网络调用；其余 plan、记忆落盘与结果处理均走真实代码。
    def success(text, target, **kwargs):
        time.sleep(.12)
        return dict(text='A local test translation.', source='zh', target=target)
    C.call_google_free = success
    app.lane_mine.set_input('本地测试原文')
    app.lane_mine.txt_in.focus_force()
    app.after(100, guarded(start_translation))

def start_translation():
    app.lane_mine.txt_in.event_generate('<Control-Return>')
    check(app.busy == 1 and app.lane_mine.btn_go.instate(['disabled']), '快捷键启动翻译并禁用按钮')
    app.translate_lane(app.lane_peer)
    check(app.busy == 1, '快速重复点击不会并发写会话')
    app.after(60, guarded(wait_success))

deadline = time.monotonic() + 15
def wait_success():
    if app.busy and time.monotonic() < deadline:
        app.after(60, guarded(wait_success))
        return
    check(app.lane_mine.get_output() == 'A local test translation.', '主窗口收到后台译文')
    check(app.clipboard_get() == 'A local test translation.', '翻译完成自动复制')
    check(len(app.t.memory('toPeer')) == 1 and not app.t.memory('fromPeer'), '两侧记忆仍独立')
    check(not app.lane_mine.btn_go.instate(['disabled']), '完成后按钮恢复')
    app.lane_mine.btn_copy.invoke()
    check(app.clipboard_get() == 'A local test translation.', '译文旁复制按钮可用')
    output = app.lane_mine.txt_out
    output.focus_force()
    app.after(100, guarded(check_output_keys))

def check_output_keys():
    output = app.lane_mine.txt_out
    output.event_generate('<Control-a>')
    check(output.get('sel.first', 'sel.last') == 'A local test translation.', '只读译文支持 Ctrl+A')
    output.event_generate('<<Paste>>')
    check(app.lane_mine.get_output() == 'A local test translation.', '粘贴不会改写只读译文')
    app.lane_mine.txt_in.focus_force()
    app.lane_mine.txt_in.event_generate('<Tab>')
    check(app.focus_get() is app.lane_mine.btn_go, 'Tab 从输入框移到翻译按钮')
    # 回填保留原文，历史窗口隐藏不影响主界面输入。
    app.lane_mine.tree.selection_set(app.lane_mine.tree.get_children()[0])
    app.lane_mine._recall()
    check(app.lane_mine.get_input() == '本地测试原文', '记忆回填原文')
    def failure(*args, **kwargs):
        time.sleep(.12)
        raise C.ApiError('本地模拟：服务暂不可用')
    C.call_google_free = failure
    app.overlay.set_input('测试失败处理')
    app.overlay.btn_go.invoke()
    app.overlay.set_side('fromPeer')
    check(app.overlay.side == 'toPeer', '翻译过程中方向保持稳定')
    app.after(60, guarded(wait_failure))

def wait_failure():
    if app.busy and time.monotonic() < deadline:
        app.after(60, guarded(wait_failure))
        return
    check('服务暂不可用' in app.overlay.lbl_hint.cget('text'), '悬浮窗直接显示翻译错误')
    check(not app.overlay.btn_go.instate(['disabled']) and app.busy == 0, '失败后按钮可重试')
    check(not callbacks, '工作线程回调无异常')
    finish()

def finish():
    app.clipboard_clear()
    if original_clipboard is not None:
        app.clipboard_append(original_clipboard)
    app.on_close()
    check(before == user_hashes(), '真实配置和会话哈希未变')
    print(json.dumps(dict(passed=len(passed), failures=errors, checks=passed), ensure_ascii=False))

app.after(400, guarded(start))
app.after(16000, guarded(finish))
app.mainloop()
sys.exit(bool(errors))
