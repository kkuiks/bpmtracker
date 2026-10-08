"""Provide member login through a local browser viewer."""
import argparse
import json
import os
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright


REPO = Path(__file__).resolve().parents[2]
PRIVATE = REPO / 'data/private/ntm'


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    os.chmod(path, 0o600)


HTML = '''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>NTM 로그인</title><style>
body{font:16px system-ui;background:#17191d;color:#eee;margin:20px}
main{max-width:1100px;margin:auto}p{line-height:1.6}button{padding:9px 14px}
img{width:100%;outline:none;border:1px solid #555;cursor:pointer}#where{overflow-wrap:anywhere}
</style><main><h2>Nail The Mix 실제 로그인 화면</h2>
<p>아래 화면을 클릭해 입력하세요. Tab·Enter·붙여넣기도 사용할 수 있습니다.
비밀번호는 채팅에 보내지 마세요.</p><p id="where">연결 중…</p>
<img id="screen" tabindex="0" alt="실제 NTM 브라우저 화면">
<p id="status"></p></main><script>
const token=__TOKEN__,screen=document.getElementById('screen');let queue=Promise.resolve();
function action(data){queue=queue.then(()=>fetch('/action',{method:'POST',headers:{
'Content-Type':'application/json','X-NTM-Login':token},body:JSON.stringify(data)}));return queue;}
screen.onclick=e=>{screen.focus();const r=screen.getBoundingClientRect();action({kind:'click',
x:(e.clientX-r.left)*1100/r.width,y:(e.clientY-r.top)*760/r.height});};
screen.onkeydown=e=>{if(e.key==='F11')return;if(e.ctrlKey||e.metaKey){
if(e.key.toLowerCase()==='a'){e.preventDefault();action({kind:'key',key:'Control+A'});}return;}
e.preventDefault();if(e.key.length===1)action({kind:'text',text:e.key});
else if(['Enter','Tab','Backspace','Delete','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key))action({kind:'key',key:e.shiftKey?'Shift+'+e.key:e.key});};
screen.onpaste=e=>{e.preventDefault();action({kind:'text',text:e.clipboardData.getData('text')});};
screen.onwheel=e=>{e.preventDefault();action({kind:'scroll',dy:e.deltaY});};
async function refresh(){try{const r=await fetch('/frame',{headers:{'X-NTM-Login':token}});
const b=await r.blob(),old=screen.src;screen.src=URL.createObjectURL(b);if(old.startsWith('blob:'))URL.revokeObjectURL(old);
const s=await(await fetch('/status',{headers:{'X-NTM-Login':token}})).json();
document.getElementById('where').textContent=s.url;document.getElementById('status').textContent=
s.saved?'로그인 세션이 저장되었습니다. 채팅에서 로그인 완료라고 알려주세요.':'';
}catch(e){document.getElementById('status').textContent='연결을 기다리는 중…';}setTimeout(refresh,900);}refresh();
</script></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8996)
    args = parser.parse_args()
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(PRIVATE, 0o700)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(REPO / 'data/runtime/ntm-collector/browsers')
    token = secrets.token_urlsafe(24)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=pw.chromium.executable_path)
        auth = PRIVATE / 'auth-state.json'
        context = browser.new_context(viewport={'width': 1100, 'height': 760},
                                      **({'storage_state': str(auth)} if auth.exists() else {}))
        page = context.new_page()
        state = {'saved': False, 'nonce': None}

        def request_seen(request):
            if request.url.startswith('https://members.urm.academy/'):
                nonce = request.headers.get('x-wp-nonce')
                if nonce:
                    state['nonce'] = nonce

        page.on('request', request_seen)
        page.goto('https://members.urm.academy/login/', wait_until='domcontentloaded', timeout=45000)

        def save_login():
            current = urlsplit(page.url)
            if current.hostname != 'members.urm.academy' or 'login' in current.path.lower():
                return
            if not state['saved']:
                private_json(auth, context.storage_state())
                state['saved'] = True
                print(json.dumps({'login_session_saved': True}), flush=True)
            if state['nonce']:
                private_json(PRIVATE / 'nonce.json', {'nonce': state['nonce']})

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def respond(self, data, content_type='application/json', status=200):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                route = urlsplit(self.path).path
                if route == '/':
                    self.respond(HTML.replace('__TOKEN__', json.dumps(token)).encode(), 'text/html; charset=utf-8')
                    return
                if self.headers.get('X-NTM-Login') != token:
                    self.respond(b'{}', status=403)
                    return
                try:
                    if route == '/frame':
                        frame = page.screenshot(type='jpeg', quality=75)
                        save_login()
                        self.respond(frame, 'image/jpeg')
                    elif route == '/status':
                        save_login()
                        parsed = urlsplit(page.url)
                        self.respond(json.dumps({'url': urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', '')),
                                                 'saved': state['saved']}).encode())
                    else:
                        self.respond(b'{}', status=404)
                except Exception:
                    self.respond(b'{}', status=503)

            def do_POST(self):
                if urlsplit(self.path).path != '/action' or self.headers.get('X-NTM-Login') != token:
                    self.respond(b'{}', status=403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 32768:
                        self.respond(b'{}', status=400)
                        return
                    data = json.loads(self.rfile.read(length))
                    if data['kind'] == 'click':
                        page.mouse.click(float(data['x']), float(data['y']))
                    elif data['kind'] == 'text':
                        page.keyboard.insert_text(data['text'])
                    elif data['kind'] == 'key':
                        page.keyboard.press(data['key'])
                    elif data['kind'] == 'scroll':
                        page.mouse.wheel(0, float(data['dy']))
                    save_login()
                    self.respond(b'{}')
                except Exception:
                    self.respond(b'{}', status=503)

        server = HTTPServer(('127.0.0.1', args.port), Handler)
        print(json.dumps({'login_viewer': f'http://localhost:{args.port}/', 'browser_qa_run': False}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            browser.close()


if __name__ == '__main__':
    main()
