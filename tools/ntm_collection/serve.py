"""Loopback-only exact-asset server for the new three-song offset review."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.project_storage import resolve_path, SAMPLES
import re
from urllib.parse import unquote,urlsplit


def run(root, port):
    catalog=json.loads((root/'index-data.json').read_text())
    allowed={'index.html':Path(__file__).with_name('review.html'),'index-data.json':root/'index-data.json'}
    for row in catalog['songs']:
        allowed[row['review']]=resolve_path(SAMPLES/row['review'])
        data=json.loads(resolve_path(SAMPLES/row['review']).read_text())
        for name in ['audio','original_audio','raw_clock','accepted_map','approved_click','approved_audition','acceptance_record']:
            if data.get(name):allowed[data[name]]=resolve_path(SAMPLES/data[name])
        for item in data['clock_files']:allowed[item['path']]=resolve_path(SAMPLES/item['path'])
    for row in catalog.get('source_only_songs',[]):
        allowed[row['audio']]=resolve_path(SAMPLES/row['audio'])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_HEAD(self):self.send_asset(False)
        def do_GET(self):self.send_asset(True)
        def send_asset(self,body):
            name=unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            if name not in allowed:
                self.send_error(404);return
            path=allowed[name];size=path.stat().st_size;start=0;end=size-1
            requested=self.headers.get('Range')
            if requested:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
                if not match:self.send_error(416);return
                start=int(match[1]);end=min(end,int(match[2])) if match[2] else end
                if start>end:self.send_error(416);return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
            self.send_header('Cache-Control','no-store')
            if requested:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if body:
                try:
                    with path.open('rb') as f:
                        f.seek(start);left=end-start+1
                        while left:
                            block=f.read(min(left,1024*1024));self.wfile.write(block);left-=len(block)
                except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(json.dumps(dict(review=f'http://localhost:{port}/',songs=len(catalog['songs']),allowed_assets=len(allowed))),flush=True)
    server.serve_forever()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8990);a=p.parse_args();run(a.root.resolve(),a.port)
