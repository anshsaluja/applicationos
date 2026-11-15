"""Reject unsafe smoke targets before making any network requests.

The smoke runner is intentionally restricted to loopback HTTP. These tests
exercise its startup guard without requiring Docker or PostgreSQL.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_local_journey.py"


class SmokeTargetSafetyTests(unittest.TestCase):
    def test_external_and_ambiguous_targets_are_rejected(self):
        targets = (
            "https://127.0.0.1:8000",
            "http://example.com:8000",
            "http://127.0.0.1.evil.example:8000",
            "http://user:pass@127.0.0.1:8000",
            "http://127.0.0.1:8000/other",
            "http://127.0.0.1:8000?redirect=1",
            "http://127.0.0.1:8000/#fragment",
            "file:///etc/passwd",
        )
        for target in targets:
            with self.subTest(target=target):
                env = os.environ.copy()
                env["APPLICATIONOS_SMOKE_API_URL"] = target
                result = subprocess.run(
                    [sys.executable, str(SCRIPT)], cwd=ROOT, env=env,
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing unsafe or non-local smoke test target", result.stderr)

    def test_synthetic_execution_rejects_remote_database_before_http(self):
        targets = (
            "postgresql+psycopg://tester:pass@db.example.com:5432/test",
            "postgresql+psycopg://tester:pass@localhost:5432/test?hostaddr=203.0.113.1",
            "postgresql+psycopg://tester:pass@localhost:5432/test?service=remote",
            "sqlite:///tmp/test.db",
        )
        for database_url in targets:
            with self.subTest(database_url=database_url):
                env = os.environ.copy()
                env.update({
                    "APPLICATIONOS_SMOKE_API_URL": "http://127.0.0.1:8000",
                    "APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION": "local-only",
                    "APPLICATIONOS_SMOKE_REVIEW_TOKEN": "disposable-test-token",
                    "DATABASE_URL": database_url,
                })
                result = subprocess.run(
                    [sys.executable, str(SCRIPT)], cwd=ROOT, env=env,
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires explicitly local PostgreSQL", result.stderr)
                self.assertNotIn("Connection refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
