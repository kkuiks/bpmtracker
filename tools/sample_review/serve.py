"""Serve selected owner-review assets and save separate, version-bound decisions."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import unquote, urlsplit

CHECKS = ("listened", "tempo", "meter", "alignment", "coverage")
VERDICTS = {"unreviewed", "valid", "redundant", "context", "needs_correction", "unknown"}
STATUSES = {"draft", "confirmed_current_scope", "needs_correction", "insufficient_evidence", "candidate_reviewed"}


def save(path, value):
    temporary = path.with_suffix(path.suffix+".partial")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)


def serve(root, port):
    index = json.loads((root/"index-data.json").read_text())
    assets = json.loads((root/"assets.json").read_text())["assets"]
    packets = {row["id"]:json.loads((root/row["packet_url"]).read_text()) for row in index["tracks"]}
    frontend = Path(__file__).parent/"web"
    routes = {name:dict(path=str(frontend/name)) for name in ("index.html","app.js","style.css")}
    routes["index-data.json"] = dict(path=str(root/"index-data.json"))
    routes.update({row["packet_url"]:dict(path=str(root/row["packet_url"])) for row in index["tracks"]})
    routes.update(assets)
    token = secrets.token_urlsafe(24)
    lock = threading.Lock()

    def records():
        return json.loads((root/"review-records.json").read_text())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value, status=200):
            blob = (json.dumps(value,ensure_ascii=False)+"\n").encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(blob)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            try:
                self.wfile.write(blob)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_HEAD(self):
            self.asset(False)

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/api/state":
                with lock:
                    state = records()
                self.send_json(dict(records=state["records"], session_token=token))
                return
            if route == "/api/export":
                with lock:
                    state = records()
                self.send_json(dict(**state, exported_at_utc=datetime.now(timezone.utc).isoformat(),
                                    catalog_sha256=index["catalog_sha256"], scope_counts=index["counts"],
                                    original_references_modified=False))
                return
            self.asset(True)

        def asset(self, body):
            name = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
            asset = routes.get(name)
            if asset is None:
                self.send_error(404)
                return
            path = Path(asset["path"])
            if not path.is_file():
                self.send_error(404)
                return
            stat = path.stat()
            if "mtime_ns" in asset and (stat.st_mtime_ns != asset["mtime_ns"] or stat.st_size != asset["size"]):
                self.send_json(dict(error="검토 준비 후 원본 파일이 바뀌었습니다. 새 검토 자료를 준비해 주세요."),409)
                return
            start, end = 0, stat.st_size-1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    start = stat.st_size
                elif match[1]:
                    start = int(match[1])
                    if match[2]:
                        end = min(end,int(match[2]))
                elif int(match[2]) > 0:
                    start = max(0,stat.st_size-int(match[2]))
                else:
                    start = stat.st_size
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range",f"bytes */{stat.st_size}")
                    self.send_header("Content-Length","0")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            mime = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(path.name)[0]
            self.send_header("Content-Type",mime or "application/octet-stream")
            self.send_header("Content-Length",str(max(0,end-start+1)))
            self.send_header("Accept-Ranges","bytes")
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if requested:
                self.send_header("Content-Range",f"bytes {start}-{end}/{stat.st_size}")
            self.end_headers()
            if body:
                try:
                    with path.open("rb") as stream:
                        stream.seek(start)
                        left = end-start+1
                        while left:
                            block = stream.read(min(left,1024*1024))
                            if not block:
                                break
                            self.wfile.write(block)
                            left -= len(block)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_POST(self):
            route = urlsplit(self.path).path
            if not route.startswith("/api/review/") or self.headers.get("X-Review-Session") != token:
                self.send_error(403)
                return
            ident = unquote(route.removeprefix("/api/review/"))
            packet = packets.get(ident)
            if packet is None:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length","0"))
                if not 0 < length <= 128*1024:
                    raise ValueError("검토 기록의 크기가 올바르지 않습니다.")
                incoming = json.loads(self.rfile.read(length))
                status = incoming.get("status")
                if status not in STATUSES or incoming.get("reference_sha256") != packet["reference_sha256"]:
                    raise ValueError("검토 상태 또는 지도 버전이 일치하지 않습니다.")
                for name in (packet["audio_url"], packet["reference_url"]):
                    item = assets[name]
                    stat = Path(item["path"]).stat()
                    if stat.st_size != item["size"] or stat.st_mtime_ns != item["mtime_ns"]:
                        raise ValueError("검토 대상 파일이 바뀌었습니다. 이 버전의 결과를 저장할 수 없습니다.")
                keys = {r["key"] for r in packet["tempos"]+packet["meters"]+packet["issues"]}
                decisions = incoming.get("decisions",{})
                if not isinstance(decisions,dict) or set(decisions)-keys:
                    raise ValueError("알 수 없는 지도 항목이 포함되어 있습니다.")
                if any(v not in VERDICTS for v in decisions.values()):
                    raise ValueError("항목 판정이 올바르지 않습니다.")
                checks = {key:incoming.get("checks",{}).get(key) is True for key in CHECKS}
                delta = float(incoming.get("comparison_offset_ms",0))
                if not (-600000 <= delta <= 600000):
                    raise ValueError("비교 오프셋 범위를 확인해 주세요.")
                note = incoming.get("note","")
                if not isinstance(note,str) or len(note)>12000:
                    raise ValueError("메모가 올바르지 않습니다.")
                if status == "confirmed_current_scope":
                    if packet["group"] == "candidate" or not packet["available_map"]:
                        raise ValueError("미승인 후보는 정식 표본 재검증 완료에 포함할 수 없습니다.")
                    if abs(delta)>1e-9:
                        raise ValueError("현재 지도 확인은 비교 오프셋을 0 ms로 되돌린 뒤 저장해 주세요.")
                    if not all(checks.values()):
                        raise ValueError("청취·템포·박자·정렬·범위 확인을 모두 표시해 주세요.")
                    if any(decisions.get(key,"unreviewed") not in {"valid","redundant","context"} for key in keys):
                        raise ValueError("모든 지도 항목과 점검 메모를 판정해 주세요. 미확인 또는 수정 필요 항목이 남아 있습니다.")
                if status in {"needs_correction","insufficient_evidence"} and not note.strip():
                    raise ValueError("수정/보류의 이유를 메모에 남겨 주세요.")
                coverage = incoming.get("played_intervals",[])
                if not isinstance(coverage,list) or len(coverage)>2000:
                    raise ValueError("청취 구간 기록을 확인해 주세요.")
                played = []
                for interval in coverage:
                    if not isinstance(interval,list) or len(interval)!=2:
                        raise ValueError("청취 구간이 올바르지 않습니다.")
                    a,b = map(float,interval)
                    if not (0<=a<=b<=packet["duration_seconds"]+.1):
                        raise ValueError("청취 구간이 음원 범위를 벗어납니다.")
                    played.append([a,b])
                with lock:
                    state = records()
                    prior = state["records"].get(ident,{})
                    result = dict(id=ident,title=packet["title"],group=packet["group"],status=status,
                        revision=prior.get("revision",0)+1, saved_at_utc=datetime.now(timezone.utc).isoformat(),
                        reference_sha256=packet["reference_sha256"], reference_path=packet["reference_path"],
                        audio_path=packet["audio_path"], audio_catalog_sha256=packet["audio_catalog_sha256"],
                        audio_bytes_hash_verified=False, catalog_sha256=index["catalog_sha256"],
                        checks=checks,decisions=decisions,note=note,comparison_offset_ms=delta,
                        stored_offset_seconds=packet["stored_offset_seconds"],
                        proposed_offset_seconds=(packet["stored_offset_seconds"]+delta/1000 if packet["stored_offset_seconds"] is not None else None),
                        verified_map_scope_seconds=packet["support_seconds"],
                        no_grid_seconds=packet["no_grid_seconds"],played_intervals=played,
                        playback_intervals_are_not_automatic_acceptance=True,
                        owner_attestation_only=True, independent_millisecond_certification=False,
                        original_reference_modified=False)
                    with (root/"review-history.jsonl").open("a",encoding="utf-8") as history:
                        history.write(json.dumps(result,ensure_ascii=False)+"\n")
                    state["records"][ident]=result
                    save(root/"review-records.json",state)
                self.send_json(dict(saved=True,record=result))
            except (ValueError,TypeError,KeyError,json.JSONDecodeError) as error:
                self.send_json(dict(error=str(error)),400)

    server = ThreadingHTTPServer(("127.0.0.1",port),Handler)
    print(json.dumps(dict(review_url=f"http://localhost:{port}/",counts=index["counts"],
                          results_directory=str(root),original_references_modified=False),ensure_ascii=False),flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--port",type=int,default=9010)
    args = parser.parse_args()
    serve(args.root.resolve(),args.port)
