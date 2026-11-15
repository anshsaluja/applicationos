"""Verify redirects never replay synthetic HTTP requests, including POST bodies.

All requests target a disposable loopback server. A redirect response must not
trigger a second request, even if its Location points back to that server.
"""
import http.server
import importlib.util
from pathlib import Path
import threading
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_local_journey.py"


class RedirectServer(http.server.BaseHTTPRequestHandler):
    hits = []
    redirect_code = 307

    def respond(self):
        self.hits.append((self.command, self.path))
        if self.path == "/start":
            self.send_response(self.redirect_code)
            self.send_header("Location", "/destination")
        else:
            self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def log_message(self, format, *args):
        pass


class RedirectReplayTests(unittest.TestCase):
    def test_redirects_do_not_replay_get_or_post(self):
        spec = importlib.util.spec_from_file_location("smoke_local_journey", SCRIPT)
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        server = http.server.HTTPServer(("127.0.0.1", 0), RedirectServer)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for status in (301, 302, 303, 307, 308):
                for method in ("GET", "POST"):
                    with self.subTest(status=status, method=method):
                        RedirectServer.hits = []
                        RedirectServer.redirect_code = status
                        url = f"http://127.0.0.1:{server.server_port}/start"
                        body = b'{"synthetic":true}' if method == "POST" else None
                        req = smoke.urllib.request.Request(url, data=body, method=method)
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            smoke.opener.open(req, timeout=3)
                        self.assertEqual(error.exception.code, status)
                        self.assertEqual(RedirectServer.hits, [(method, "/start")])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
