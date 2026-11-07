#!/usr/bin/env python3
"""Hands the screen its page and the latest snapshot, on this Pi only. It serves these four paths and nothing else. With --wait, it waits until the server is answering."""
import http.server
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(os.environ.get("THESEUS_WALL_DISPLAY", Path(__file__).resolve().parents[1] / "display"))
RUN = Path(os.environ.get("THESEUS_WALL_RUN", "/run/theseus-wall"))
PORT = int(os.environ.get("THESEUS_WALL_PORT", "8737"))
FILES = {
    "/": (HERE / "index.html", "text/html; charset=utf-8"),
    "/wall.js": (HERE / "wall.js", "text/javascript; charset=utf-8"),
    "/wall.css": (HERE / "wall.css", "text/css; charset=utf-8"),
    "/wall.json": (RUN / "wall.json", "application/json; charset=utf-8"),
}
POLICY = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; font-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hit = FILES.get(self.path.split("?")[0])
        if not hit:
            return self.send_error(404)
        try:
            body = hit[0].read_bytes()
        except OSError:
            return self.send_error(404)  # no snapshot yet: the page shows Waiting
        self.send_response(200)
        self.send_header("Content-Type", hit[1])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", POLICY)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # nothing about your list goes in a log


def wait(seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", PORT), 1).close()
            return 0
        except OSError:
            time.sleep(0.5)
    return 1


def main():
    if "--wait" in sys.argv:
        return wait()
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
