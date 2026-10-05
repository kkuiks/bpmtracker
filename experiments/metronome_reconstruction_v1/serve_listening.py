"""Serve only the listening page and its explicitly selected assets on loopback."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def serve(root, port):
    frontend = Path(__file__).parent / "listening"
    data = json.loads((root / "index-data.json").read_text(encoding="utf-8"))
    routes = json.loads((root / "assets.json").read_text(encoding="utf-8"))["assets"]
    requested = {track[key] for track in data["tracks"] for key in ("audio_url", "map_url")}
    allowed = {name: Path(routes[name]) for name in requested}
    allowed.update({name: frontend / name for name in ("index.html", "app.js", "style.css")})
    allowed["index-data.json"] = root / "index-data.json"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_asset(True)

        def do_HEAD(self):
            self.send_asset(False)

        def send_asset(self, body):
            name = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
            path = allowed.get(name)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            start, end = 0, size - 1
            requested_range = self.headers.get("Range")
            if requested_range:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested_range)
                if match and (match[1] or match[2]):
                    if match[1]:
                        start = int(match[1])
                        if match[2]:
                            end = min(end, int(match[2]))
                    elif int(match[2]) > 0:
                        start = max(0, size - int(match[2]))
                    else:
                        start = size
                else:
                    start = size
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if requested_range else 200)
            mime = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(path.name)[0]
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if requested_range:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if body:
                try:
                    with path.open("rb") as stream:
                        stream.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            block = stream.read(min(remaining, 1024 * 1024))
                            if not block:
                                break
                            self.wfile.write(block)
                            remaining -= len(block)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"listening_page": f"http://localhost:{server.server_port}/",
                      "songs": len(data["tracks"]), "allowed_assets": len(allowed),
                      "run": data["run"], "condition": data["condition"]}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8997)
    args = parser.parse_args()
    serve(args.root.absolute(), args.port)
