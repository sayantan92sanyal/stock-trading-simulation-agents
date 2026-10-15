"""Local HTTP server for the live debate viewer. Serves the static page, icons, and the debate JSON API."""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import debate as deb

ROOT = Path(__file__).resolve().parent.parent
VIEWER_HTML = ROOT / "web" / "viewer.html"
ICONS_DIR = ROOT / "web" / "icons"

DEFAULT_PORT = 8765


class DebateHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        if not path.exists():
            self._send_json(404, {"error": f"not found: {path.name}"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/viewer.html":
            self._send_file(VIEWER_HTML, "text/html")
        elif self.path.startswith("/icons/") and self.path.endswith(".png"):
            name = self.path[len("/icons/"):]
            self._send_file(ICONS_DIR / name, "image/png")
        elif self.path == "/api/debates":
            self._send_json(200, deb.list_debates())
        elif self.path.startswith("/api/debate/"):
            debate_id = self.path[len("/api/debate/"):]
            try:
                self._send_json(200, deb.show_debate(debate_id))
            except FileNotFoundError:
                self._send_json(404, {"error": f"no debate found for {debate_id!r}"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


def serve(port=DEFAULT_PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), DebateHandler)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(prog="debate_server.py")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    print(f"Serving debate viewer on http://localhost:{args.port}/")
    serve(args.port)


if __name__ == "__main__":
    main()
