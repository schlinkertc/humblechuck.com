"""Local-only catalog and range-capable audio server for the supplied demo."""

from datetime import datetime, timezone
from functools import partial
from hashlib import md5
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
from threading import Lock
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infrastructure.demos.catalog import track_from_object
from infrastructure.demos import plays

SEED = Path(os.environ.get("DEMO_PREVIEW_RECORDINGS_DIR", ROOT / "recordings" / "seed"))
PLAY_EVENTS = set()
PLAY_COUNTS = {}
PLAY_LOCK = Lock()


class PreviewHandler(SimpleHTTPRequestHandler):
    def json_response(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/demo-plays":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid body length")
            item, _ = plays.parse_play({"headers": dict(self.headers), "body": self.rfile.read(length).decode()})
        except (ValueError, TypeError, UnicodeError):
            self.json_response(400, {"error": "Invalid play event."})
            return
        key = item["demo_id"]["S"]
        filename = key.removeprefix("tracks/")
        if "/" in filename or not (SEED / filename).is_file():
            self.json_response(404, {"error": "Recording not found."})
            return
        with PLAY_LOCK:
            event_key = (key, item["event_id"]["S"])
            recorded = event_key not in PLAY_EVENTS
            if recorded:
                PLAY_EVENTS.add(event_key)
                PLAY_COUNTS[key] = PLAY_COUNTS.get(key, 0) + 1
            count = PLAY_COUNTS.get(key, 0)
        self.json_response(200, {"demo_id": key, "plays": count, "recorded": recorded})

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/api/demo-plays":
            try:
                key = plays.demo_key(parse_qs(urlsplit(self.path).query).get("demo_id", [None])[0])
            except (ValueError, TypeError, UnicodeError):
                self.json_response(400, {"error": "Invalid demo ID."})
                return
            with PLAY_LOCK:
                count = PLAY_COUNTS.get(key, 0)
            self.json_response(200, {"demo_id": key, "plays": count})
        elif path == "/api/demos":
            tracks = []
            for file in sorted(SEED.iterdir()):
                if not file.is_file():
                    continue
                track = track_from_object({
                    "Key": f"tracks/{file.name}", "Size": file.stat().st_size,
                    "ETag": md5(file.read_bytes()).hexdigest(),
                    "LastModified": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc),
                })
                if track:
                    tracks.append(track)
            data = json.dumps({"tracks": tracks}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/tracks/"):
            name = path.removeprefix("/tracks/")
            file = SEED / name
            if "/" in name or name in {".", ".."} or not file.is_file():
                self.send_error(404)
                return
            size = file.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                if not match:
                    self.send_error(416)
                    return
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
                if start > end:
                    self.send_error(416)
                    return
            self.send_response(206 if range_header else 200)
            self.send_header("Content-Type", "audio/mp4" if file.suffix == ".m4a" else self.guess_type(str(file)))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            if range_header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with file.open("rb") as audio:
                audio.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = audio.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        else:
            super().do_GET()


if __name__ == "__main__":
    print("Local preview: http://127.0.0.1:8000/demos/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), partial(PreviewHandler, directory=str(ROOT / "dist"))).serve_forever()
