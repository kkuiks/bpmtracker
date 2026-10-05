"""Serve only the completed review and its explicitly listed native artifacts."""
import argparse
from http.server import ThreadingHTTPServer
import json
from pathlib import Path

from .prepare import digest
from experiments.tempo_meter_v3.serve_gate_review import handler


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--port',type=int,default=8985);a=p.parse_args()
    run=a.run.resolve();files={}
    for item in json.loads((run/'review-files.json').read_text()):
        path=(run/item['path']).resolve()
        if not path.is_relative_to(run) or digest(path)!=item['sha256']:raise ValueError('review file binding changed')
        files['/'+item['path']]=path
    server=ThreadingHTTPServer(('127.0.0.1',a.port),handler(files))
    print(f'Commercial review: http://localhost:{a.port}/review/index.html; {len(files)} bound files',flush=True)
    server.serve_forever()


if __name__=='__main__':main()
