"""Validate pipes, Unicode, errors and cancellation in the windowed EXE worker."""
import hashlib,json,os,subprocess,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import translator_core as C
real=Path(C.default_user_data_dir())
def hashes():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in real.glob('pretend_foreigner.*.json')}
before=hashes();received=threading.Event();release=threading.Event()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value,status=200):
        body=json.dumps(value).encode()
        try:
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except (ConnectionResetError,BrokenPipeError):pass
    def do_GET(self):
        if self.path.startswith('/slow'):received.set();release.wait(8)
        if self.path.startswith('/bad'):self.reply(dict(error='fixture unauthorized'),401)
        else:self.reply(dict(data=[dict(id='模型一'),dict(id='model-two')]))
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.reply(dict(choices=[dict(message=dict(content=json.dumps(dict(text='测试已连通。',source='zh',target='en',mode='precise'))))]))
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
exe=Path(sys.argv[1])
children=[];passed=[]
def job(kind,tag):
    child=subprocess.Popen([str(exe),'--provider-probe'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,encoding='utf-8',text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    children.append(child)
    payload=json.dumps(dict(kind=kind,base='http://127.0.0.1:%d/%s'%(server.server_port,tag),
                            key='local-fixture-key',model='fixture',proxy=False),ensure_ascii=False)
    return child,payload
def check(value,label):assert value,label;passed.append(label)
try:
    for kind in ('models','chat'):
        child,payload=job(kind,'good');stdout,_stderr=child.communicate(payload,timeout=15)
        result=json.loads(stdout)
        check(child.returncode==0 and result['ok'],'EXE '+kind+' worker uses inherited pipes')
        check('模型一' in result['value'] if kind=='models' else result['value']['text']=='测试已连通。','EXE '+kind+' Unicode result')
    child,payload=job('models','bad');stdout,_=child.communicate(payload,timeout=15)
    result=json.loads(stdout);check(not result['ok'] and '401' in result['error'],'EXE error is structured')
    child,payload=job('models','slow')
    reader=threading.Thread(target=lambda:child.communicate(payload),daemon=True);reader.start()
    check(received.wait(10),'EXE slow request reached fixture server')
    start=time.monotonic();child.terminate();child.wait(timeout=3);reader.join(3)
    check(time.monotonic()-start<2 and not reader.is_alive(),'EXE cancellation stops request process promptly')
finally:
    release.set()
    for child in children:
        if child.poll() is None:child.terminate();child.wait(timeout=3)
    server.shutdown();server.server_close()
check(before==hashes(),'Real user data unchanged')
print(json.dumps(dict(ok=True,passed=passed),ensure_ascii=True))
