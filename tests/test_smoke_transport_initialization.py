"""Regression tests for the smoke client's local-only HTTP transport.

These run without Docker, PostgreSQL, or external network access.
"""
import importlib.util
from pathlib import Path
import unittest
import urllib.request

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_local_journey.py"


class SmokeTransportTests(unittest.TestCase):
    def test_proxy_free_opener_is_initialized_at_import(self):
        spec = importlib.util.spec_from_file_location("smoke_transport_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertIsInstance(module.opener, urllib.request.OpenerDirector)
        proxy_handlers = [
            handler for handler in module.opener.handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})
        self.assertTrue(any(isinstance(h, module.NoRedirect) for h in module.opener.handlers))


if __name__ == "__main__":
    unittest.main()
