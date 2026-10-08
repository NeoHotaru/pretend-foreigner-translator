"""本地主循环中的检查、后台下载、重试和保存退出交互，不联网安装。"""
import hashlib
import sys
import json
from pathlib import Path
from unittest.mock import Mock

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
import translator_core as C
C.use_sandbox_config(str(root / 'artifacts' / 'update-refresh' / 'pft_sandbox_ui'))
assert C.is_sandboxed()
C.save_json(C.CONFIG_FILE, dict(C.DEFAULT_CONFIG, setupDone=True, checkUpdates=False,
                               autoDownloadUpdates=True, asrWarmup=False, globalHotkeys=False))
import app_updates as U
import translate_app as UI

app = UI.App()
app.title('更新交互测试（沙箱）')
app.geometry('1120x740')
payload = b'local verified installer fixture'
folder = root / 'artifacts' / 'update-refresh'
package = folder / 'fixture.exe'
info = U.UpdateInfo('1.1.2', 'https://github.com/'+C.REPO_SLUG+'/releases/tag/v1.1.2',
                    'pretend-foreigner-setup-1.1.2.exe', 'https://example.invalid/fixture.exe',
                    len(payload), hashlib.sha256(payload).hexdigest())
passed, errors, callbacks = [], [], []
app.report_callback_exception = lambda *a: callbacks.append(str(a[1]))
original = (U.fetch_update, U.download_update, U.installed_directory, U.launch_installer)
U.fetch_update = lambda: info
U.installed_directory = lambda: folder / 'installed'
launch = U.launch_installer = Mock()

def fake_download(value, progress=None, cancel=None, **kwargs):
    if cancel.is_set():
        raise U.DownloadCancelled('cancelled')
    progress(10, len(payload))
    package.write_bytes(payload)
    progress(len(payload), len(payload))
    return package
U.download_update = fake_download

def check(condition, name):
    (passed if condition else errors).append(name)

def later(delay, function):
    def wrapped():
        try: function()
        except Exception as e:
            errors.append('%s: %s' % (function.__name__, e))
            finish()
    app.after(delay, wrapped)

def start():
    check(app.btn_update.winfo_rooty()+app.btn_update.winfo_height() <= app.winfo_rooty()+app.winfo_height(),
          '最小窗口仍能看到更新按钮')
    app.t.config['checkUpdates'] = True
    app.btn_update.invoke()
    check(app._update_checking and app.btn_update.instate(['disabled']), '检查更新防止重复点击')
    later(500, ready)

def ready():
    check(app._update_package == package and app.btn_update.cget('text') == '重启并更新',
          '发现新版本后自动后台下载并显示重启按钮')
    check(not app._update_checking and not app._update_downloading, '准备好后下载状态复位')
    app.busy = 1
    app.btn_update.invoke()
    check(not launch.called and not app._closing, '翻译中不会退出安装')
    app.busy = 0
    app.recording_target = app.lane_mine
    app.btn_update.invoke()
    check(not launch.called, '录音中不会退出安装')
    app.recording_target = None
    saved = app.t.save_all
    app.t.save_all = lambda: False
    app.btn_update.invoke()
    check(not launch.called and not app._closing, '保存失败阻止退出更新')
    app.t.save_all = saved
    launch.side_effect = U.UpdateError('本地模拟：安装包校验失败')
    app.btn_update.invoke()
    check(app._update_package is None and app.btn_update.cget('text') == '重试下载', '安装失败提供重试且旧程序保持运行')
    launch.reset_mock(side_effect=True)
    app.btn_update.invoke()
    later(350, retry_ready)

def retry_ready():
    check(app._update_package == package, '重试下载恢复可更新状态')
    dlg = UI.SettingsDialog(app)
    dlg.v_update_download.set(False)
    dlg.save_update_preferences()
    check(not app.t.config['autoDownloadUpdates'], '设置可以关闭自动下载')
    dlg.destroy()
    app.v_note.set('更新前术语 = saved term')
    app.on_close = Mock()
    app.btn_update.invoke()
    check(launch.called and app.on_close.called, '点击重启按钮交给安装器并退出')
    check(app.t.note() == '更新前术语 = saved term', '退出更新前保存当前会话术语')
    check(not callbacks, '后台线程没有直接操作或破坏 Tk 控件')
    finish()

finished = False
def finish():
    global finished
    if finished: return
    finished = True
    (U.fetch_update, U.download_update, U.installed_directory, U.launch_installer) = original
    UI.App.on_close(app)
    package.unlink(missing_ok=True)
    print(json.dumps(dict(passed=len(passed), failures=errors, checks=passed), ensure_ascii=False))

later(300, start)
later(10000, lambda: (check(False, '更新交互超时'), finish()))
app.mainloop()
sys.exit(bool(errors))
