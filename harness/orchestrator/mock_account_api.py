"""Demo #10 mock 'connect account' endpoint. Records the received body to
record_path; if echo=True, echoes the body back in the response (to exercise
outbound echo-masking)."""
from __future__ import annotations
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def start_mock(port: int, record_path: str, echo: bool = False):
    """Start a localhost mock on `port`. Each POST writes {"body": <raw body>} to
    record_path; if echo, the response includes the body under "received".
    Returns the HTTPServer; caller does srv.shutdown()."""
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            body = self.rfile.read(n).decode("utf-8", "replace")
            with open(record_path, "w") as f:
                json.dump({"body": body}, f)
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            payload = {"connected": True}
            if echo:
                payload["received"] = body
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *a):  # silence
            pass
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
