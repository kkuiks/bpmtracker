"""Loopback-only exact-allowlist server for a gate-1 review bundle."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .probe_resources import digest


def allowed_files(root):
    files={}
    for item in json.loads((root/'review/files.json').read_text()):
        path=(root/'review'/item['path']).resolve()
        if not path.is_relative_to((root/'review').resolve()) or digest(path)!=item['sha256']:
            raise ValueError('review manifest binding failed')
        files['/review/'+item['path']]=path
    for name in ['RESULTS.md','data-inventory.json','resources.json']:
        if (root/name).is_file():files['/'+name]=(root/name).resolve()
    return files


def handler(files):
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):self.respond(False)
        def do_GET(self):self.respond(True)
        def respond(self,body):
            path=unquote(urlsplit(self.path).path)
            if path in ('/','/review','/review/'):
                self.send_response(302);self.send_header('Location','/review/index.html');self.end_headers();return
            if path not in files:
                self.send_error(404);return
            target=files[path]
            self.send_response(200)
            self.send_header('Content-Type',mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(target.stat().st_size))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            if body:
                with target.open('rb') as source:
                    while block:=source.read(65536):self.wfile.write(block)
    return Handler


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8973);a=p.parse_args()
    files=allowed_files(a.root.resolve())
    server=ThreadingHTTPServer(('127.0.0.1',a.port),handler(files))
    print(f'Gate 1: http://localhost:{a.port}/review/index.html ({len(files)} allowlisted files)',flush=True)
    server.serve_forever()


if __name__=='__main__':main()
