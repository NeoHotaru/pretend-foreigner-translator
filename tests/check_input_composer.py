"""Actual Tk + Windows backfill checks; isolated user data and local fake translations."""
import ctypes
import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import translator_core as C
real_dir = Path(C.default_user_data_dir())
def user_hashes():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real_dir.glob('pretend_foreigner.*.json')}
before = user_hashes()
folder = ROOT / 'artifacts' / 'input-preview'
folder.mkdir(parents=True, exist_ok=True)
C.use_sandbox_config(str(folder / 'pft_sandbox_gui'))
assert C.is_sandboxed()
config = dict(C.DEFAULT_CONFIG, setupDone=True, checkUpdates=False, asrWarmup=False,
              globalHotkeys=False, activeBackend='provider:fixture', providers=[
                  dict(name='fixture', apiKey='local-test-fixture', baseUrl='http://example.invalid', model='fixture')])
C.save_json(C.CONFIG_FILE, config)
C.save_json(C.SESSION_FILE, {'active':'会话 1','list':[C.new_session('会话 1')]})
import translate_app as UI
import input_composer as IC
from input_target import capture_target, user32, PartialInsertError

app = UI.App()
app.title('翻译输入本地检查 · 沙箱')
app.withdraw()
app.open_input_composer()
composer = app.input_composer
composer.cancel()
errors=[];passed=[];callbacks=[];calls=[]
app.report_callback_exception=lambda *a:callbacks.append(str(a[1]))
gate = threading.Event();gate.set()

def runner(key):
    def translate(sp,text):
        calls.append((sp,text))
        gate.wait(5)
        return json.dumps(dict(text='make the floating island smaller lol', source='zh', target='en', mode='casual'))
    return translate

fixture = subprocess.Popen([sys.executable,str(ROOT/'tests/input_target_fixture.py')],stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
messages=queue.Queue()
def receive():
    for line in fixture.stdout:
        messages.put(json.loads(line))
threading.Thread(target=receive,daemon=True).start()

def tick_until(predicate, timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.update();composer.pump()
        if predicate():return
        time.sleep(.015)
    raise AssertionError('Timed out waiting for local fixture or UI')

def command(action, **kwargs):
    fixture.stdin.write(json.dumps(dict(action=action,**kwargs))+'\n');fixture.stdin.flush()
    tick_until(lambda:not messages.empty())
    return messages.get()

def prepare_target():
    prepared=command('prepare')
    # A real click grants foreground activation in Windows. Verify the window
    # under this fixture-only label before issuing that click.
    from ctypes import wintypes
    u=user32()
    u.WindowFromPoint.argtypes=[wintypes.POINT]
    u.WindowFromPoint.restype=wintypes.HWND
    x,y=prepared['click']
    u.SetCursorPos(x,y)
    hit=u.WindowFromPoint(wintypes.POINT(x,y))
    pid=wintypes.DWORD();u.GetWindowThreadProcessId(hit,ctypes.byref(pid))
    assert pid.value==prepared['pid'], '测试区域被遮挡，停止输入'
    u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
    command('prepare')
    captured=[]
    def focused():
        try:
            target=capture_target()
        except Exception:
            return False
        if target.process_id==prepared['pid']:
            captured.append(target)
            return True
        return False
    tick_until(focused)
    return captured[0]

def set_source(text):
    composer.txt_in.delete('1.0','end');composer.txt_in.insert('1.0',text)
    composer.txt_in.edit_modified(True);app.update()

def preview(target, keyboard=False):
    composer.show(target)
    set_source('那个悬浮窗再小一点，哈哈。')
    if keyboard:
        composer.txt_in.event_generate('<Control-Return>');app.update()
        check(composer.txt_in.get('1.0','end-1c')=='那个悬浮窗再小一点，哈哈。','Ctrl+Enter不在原稿中插入换行')
    else:
        composer.request_preview()
    tick_until(lambda:not composer.busy)
    assert composer.draft.result

def check(value,label):
    if not value:raise AssertionError(label)
    passed.append(label)

try:
    tick_until(lambda:not messages.empty());messages.get()
    u=user32();clipboard_before=u.GetClipboardSequenceNumber()
    with patch.object(C.Translator,'_runner',side_effect=runner):
        target=prepare_target()
        preview(target, keyboard=True)
        check(len(app.t.memory('toPeer'))==0,'预览不写入记忆')
        command('read')
        check(not composer.btn_insert.instate(['disabled']),'预览就绪才允许填入')
        # Restore popup after the read command without touching destination focus.
        composer.lift();composer.focus_force()
        composer.txt_in.focus_set();app.update()
        composer.txt_in.event_generate('<Control-Shift-Return>');app.update()
        tick_until(lambda:not composer.inserting)
        # SendInput queues events; let the separate editor dispatch all characters.
        end=time.monotonic()+.25
        tick_until(lambda:time.monotonic()>=end)
        got=command('read')
        print(json.dumps({'insertion':got,'status':composer.lbl_status.cget('text'),
                          'memory':len(app.t.memory('toPeer')),'target':str(target)},ensure_ascii=True))
        check(got['value']=='保留前缀｜make the floating island smaller lol','真实原输入框仅替换选区，保留前缀')
        check(got['returns']==0,'回填不触发Enter或发送')
        check(len(app.t.memory('toPeer'))==1,'确认回填后记忆恰好增加一次')
        check(u.GetClipboardSequenceNumber()==clipboard_before,'回填全程不改剪贴板')

        target=prepare_target()
        composer.show(target);set_source('旧句子')
        gate.clear();composer.request_preview();set_source('新句子')
        gate.set();tick_until(lambda:not composer.busy)
        check(composer.draft.result is None and composer.btn_insert.instate(['disabled']),'请求期间改字，旧译文不能回填')

        composer.show(target);set_source('取消的句子')
        gate.clear();composer.request_preview();composer.cancel();gate.set()
        tick_until(lambda:not composer.busy)
        check(not composer.opened and composer.draft.result is None,'取消后迟到结果不复活面板')
        check(len(app.t.memory('toPeer'))==1,'取消预览不污染记忆')

        target=prepare_target();preview(target)
        set_source('已预览之后又改字')
        check(composer.btn_insert.instate(['disabled']),'预览之后改字立即禁用填入')

        target=prepare_target();preview(target)
        app.t.add_session('另一会话');app.sync_views();composer.pump()
        check(composer.draft.result is None and composer.btn_insert.instate(['disabled']),'换会话不把旧预览写进新会话')

        target=prepare_target();preview(target)
        failure_memory=len(app.t.memory('toPeer'))
        command('second')
        app.update()
        composer.lift();composer.focus_force();composer.confirm_insert()
        tick_until(lambda:not composer.inserting)
        got=command('read')
        print(json.dumps({'focus_change':got,'status':composer.lbl_status.cget('text'), 'before':failure_memory,
                          'memory':len(app.t.memory('toPeer'))},ensure_ascii=True))
        check(got['value']=='保留前缀｜替换这一段','目标焦点改变时不误写原输入框')
        check(got['second']=='','不误填入另一输入框')
        check(len(app.t.memory('toPeer'))==failure_memory,'回填失败不增加记忆')

        target=prepare_target();composer.show(target);set_source('拼音尚未确认')
        count=len(calls)
        with patch.object(IC,'ime_is_composing',return_value=True):composer.request_preview()
        check(len(calls)==count and not composer.busy,'拼音候选未确认时不发请求')

        target=prepare_target();preview(target)
        with patch.object(IC,'insert_text',side_effect=PartialInsertError('测试部分填入')):
            composer.confirm_insert();tick_until(lambda:not composer.inserting)
        check(composer.draft.result is None and len(app.t.memory('toPeer'))==failure_memory,'部分回填失败不自动重试，不记忆')
        composer.cancel()
        check(not callbacks,'无Tk回调异常')
        check(before==user_hashes(),'原用户配置和会话保持不变')
except Exception as error:
    errors.append(str(error))
finally:
    gate.set()
    try:command('quit')
    except Exception:pass
    try:fixture.wait(timeout=3)
    except subprocess.TimeoutExpired:fixture.terminate();fixture.wait(timeout=3)
    app.on_close()
    result={'ok':not errors and not callbacks,'passed':passed,'errors':errors,'callbacks':callbacks,
            'translation_calls':len(calls),'real_user_data_unchanged':before==user_hashes()}
    (folder/'gui-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if not result['ok']:sys.exit(1)
