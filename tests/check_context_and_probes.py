"""Slow local HTTP, real cancelled child processes, and actual context UI."""
import ctypes,hashlib,json,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.append('D:/Aconnada/Lib/site-packages')
sys.path.insert(0,str(ROOT/'artifacts/ui-refresh'))
from window_capture import window_image
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes();out=ROOT/'artifacts/context-probes';out.mkdir(parents=True,exist_ok=True)
C.use_sandbox_config(str(out/'pft_sandbox_features'))
C.save_json(C.CONFIG_FILE,dict(C.DEFAULT_CONFIG,setupDone=True,checkUpdates=False,
    asrWarmup=False,globalHotkeys=False,selectionButton=False,activeBackend='provider:fixture',providers=[
    dict(name='fixture',apiKey='fixture-key',baseUrl='http://example.invalid',model='fixture')]))
s=C.new_session('和 Maya 聊设计');s['note']='悬浮岛 = floating island'
s['toPeer']=[dict(src='那个悬浮岛小一点',out='Make the floating island smaller',srcLang='zh',tgtLang='en')]
s['fromPeer']=[dict(src='Maya can make it smaller tomorrow.',out='Maya 明天可以把它缩小。',srcLang='en',tgtLang='zh')]
C.save_json(C.SESSION_FILE,{'active':s['name'],'list':[s]})
from translate_app import App,SettingsDialog
app=App();app.title('NeoHotaru 设置与上下文测试');app.geometry('1240x860+80+60')
errors=[];app.report_callback_exception=lambda *args:errors.append(str(args[1]))
gates={k:threading.Event() for k in ('slow','changed','close')}
received={k:threading.Event() for k in gates}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value,status=200):
        data=json.dumps(value).encode()
        try:
            self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        tag=self.path.split('/')[1]
        if tag in gates:
            received[tag].set();gates[tag].wait(12)
        if tag=='bad':self.reply(dict(error='fixture unauthorized'),401)
        else:self.reply(dict(data=[dict(id='model-a'),dict(id='模型-b')]))
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.reply(dict(choices=[dict(message=dict(content=json.dumps(dict(text='测试连通。',source='zh',target='en',mode='precise'))))]))
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
def tick(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.update()
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Timeout: '+str(errors))
def settle():
    end=time.monotonic()+.2
    while time.monotonic()<end:app.update();time.sleep(.01)
passed=[]
def check(value,label):assert value,label;passed.append(label)
def base(dialog,tag):dialog.v_base.set('http://127.0.0.1:%d/%s'%(server.server_port,tag))
try:
    dialog=SettingsDialog(app);base(dialog,'slow')
    start=time.monotonic();dialog.on_models()
    check(time.monotonic()-start<.4,'慢请求不会阻塞按钮点击')
    tick(lambda:received['slow'].is_set());process=dialog._probe.current[1]
    dialog.notebook.select(1);settle()
    check(dialog.notebook.index('current')==1 and process.poll() is None,'请求中仍可切换设置分类')
    dialog.notebook.select(0);settle();window_image(dialog).save(out/'checking.png')
    dialog.cancel_probe();tick(lambda:process.poll() is not None)
    check(dialog._probe_kind is None and not dialog.btn_cancel_probe.winfo_manager(),'取消实际结束后台进程并恢复控件')
    gates['slow'].set();base(dialog,'good');dialog.on_models();tick(lambda:dialog._probe_kind is None)
    check(set(dialog.cb_model['values'])=={'model-a','模型-b'},'读取模型成功且支持中文模型名')
    dialog.on_test();tick(lambda:dialog._probe_kind is None)
    check('连接成功' in dialog.lbl_tip.cget('text'),'后台连接检测成功')
    base(dialog,'bad');dialog.on_models();tick(lambda:dialog._probe_kind is None)
    check('401' in dialog.lbl_tip.cget('text') and str(dialog.btn_models.cget('state'))=='normal','失败反馈与按钮恢复')
    base(dialog,'changed');dialog.on_models();tick(lambda:received['changed'].is_set())
    process=dialog._probe.current[1];dialog.v_model.set('保留的新模型')
    tick(lambda:process.poll() is not None);gates['changed'].set();settle()
    check(dialog.v_model.get()=='保留的新模型' and dialog._probe_kind is None,'修改字段取消旧请求，迟到结果不覆盖')
    base(dialog,'close');dialog.on_models();tick(lambda:received['close'].is_set())
    process=dialog._probe.current[1];dialog.destroy();tick(lambda:process.poll() is not None);gates['close'].set()
    check(not dialog.winfo_exists(),'关闭设置结束检测，无遗留窗口回调')
    gate=threading.Event();captured=[]
    def runner(key):
        def translate(prompt,text):
            captured.append(prompt);gate.wait(8)
            return json.dumps(dict(text='Then let Maya do it tomorrow.',source='zh',target='en',mode='casual'))
        return translate
    with patch.object(C.Translator,'_runner',side_effect=runner),patch.object(app,'clipboard_clear'),patch.object(app,'clipboard_append'):
        app.lane_mine.set_input('那就让她明天改吧。');app.on_translate_mine()
        tick(lambda:bool(captured));gate.set();tick(lambda:not app.busy)
        record=app._context_records['toPeer']
        check(record['usage']['cross'][0]['src'] in captured[0],'显示的参考消息确实在本次请求中')
        check('参考对方 1 条' in app.lane_mine.btn_context.cget('text'),'主界面出现实际参考数量')
        settle();window_image(app).save(out/'main.png')
        app.open_translation_context('toPeer');settle();view=app.context_view
        text=view.text.get('1.0','end')
        check('Maya can make it smaller tomorrow.' in text and '悬浮岛 = floating island' in text,'详情显示具体对方消息和术语')
        window_image(view).save(out/'context.png')
        app.t.memory('fromPeer')[0]['src']='后来修改的消息'
        check('Maya can make it smaller tomorrow.' in view.text.get('1.0','end'),'后续修改记忆不改动实际请求快照')
        view.destroy()
        from overlay import OverlayPanel
        app.overlay=OverlayPanel(app);app.overlay.show();settle();app.overlay.expand(animate=False,focus=True)
        settle();check(bool(app.overlay.btn_context.winfo_manager()),'悬浮岛同步当前会话的参考入口')
        window_image(app.overlay).save(out/'island.png');app.overlay.hide()
        gate.clear();app.lane_mine.set_input('新的请求');app.on_translate_mine();tick(lambda:len(captured)==2)
        old=app.t.current_session();count=len(old['toPeer'])
        app.t.add_session('另一个会话');app.load_session_into_ui();gate.set();tick(lambda:not app.busy)
        check(not app._context_records and len(old['toPeer'])==count and not app.t.memory('toPeer'),'换会话后旧结果不写入、不显示错误引用')
        check(not app.lane_mine.get_output(),'旧结果不覆盖新会话译文')
    check(not errors,'无 Tk 回调异常')
finally:
    for event in gates.values():event.set()
    app.on_close();server.shutdown();server.server_close()
check(before==hashes(),'真实配置和会话未改变')
print(json.dumps(dict(ok=True,passed=passed),ensure_ascii=True))
