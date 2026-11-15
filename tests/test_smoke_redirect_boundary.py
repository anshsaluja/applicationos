"""Prove the smoke HTTP client never follows redirects to another origin.

Uses an in-process loopback server; no Docker, database, or external network.
"""
import http.server
import importlib.util
from pathlib import Path
import threading
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_local_journey.py"


class RedirectHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://example.com/collect")
        self.end_headers()

    def log_message(self, format, *args):
        pass


class SmokeRedirectBoundaryTests(unittest.TestCase):
    def test_redirect_is_refused_without_following_location(self):
        spec = importlib.util.spec_from_file_location("smoke_local_journey", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = http.server.HTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/redirect"
            request = module.urllib.request.Request(url)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                module.opener.open(request, timeout=3)
            self.assertEqual(raised.exception.code, 302)
            self.assertEqual(raised.exception.url, url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
