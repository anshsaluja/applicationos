"""Regression tests for the local-only Docker safety boundary.

These tests use a fake docker executable: no daemon, network, volumes, or
containers are needed. They verify that remote endpoints are rejected before
the verification script attempts a daemon operation.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_local_stack.sh"


class DockerEndpointSafetyTests(unittest.TestCase):
    def run_with_endpoint(self, *, docker_host="", context_endpoint="unix:///var/run/docker.sock", docker_context=""):
        with tempfile.TemporaryDirectory() as temp:
            directory = pathlib.Path(temp)
            calls = directory / "calls"
            fake = directory / "docker"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n"
                "case \"$*\" in\n"
                "  'compose version') exit 0 ;;\n"
                "  'context show') printf '%s\\n' \"$FAKE_DOCKER_CONTEXT\" ;;\n"
                "  context\\ inspect\\ *\\ --format\\ *) "
                "printf '%s\\n' \"$FAKE_CONTEXT_ENDPOINT\" ;;\n"
                "  'info') exit 1 ;;\n"
                "  *) echo 'unexpected Docker operation' >&2; exit 99 ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": str(directory) + os.pathsep + env["PATH"],
                "DOCKER_CALL_LOG": str(calls),
                "FAKE_CONTEXT_ENDPOINT": context_endpoint,
                "DOCKER_HOST": docker_host,
                "FAKE_DOCKER_CONTEXT": docker_context or "default",
            })
            if docker_context:
                env["DOCKER_CONTEXT"] = docker_context
            else:
                env.pop("DOCKER_CONTEXT", None)
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=15, check=False,
            )
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_remote_docker_host_is_rejected_before_context_or_daemon_access(self):
        for endpoint in ("ssh://build.example", "tcp://127.0.0.1:2375", "https://build.example"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(docker_host=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local DOCKER_HOST", result.stderr)
                self.assertEqual(calls, ["compose version"])

    def test_remote_context_is_rejected_before_daemon_access(self):
        for endpoint in ("ssh://build.example", "tcp://127.0.0.1:2375", "https://build.example"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(context_endpoint=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local Docker context endpoint", result.stderr)
                self.assertEqual(calls, [
                    "compose version",
                    "context show",
                    "context inspect default --format {{.Endpoints.docker.Host}}",
                ])

    def test_explicit_remote_context_is_rejected_before_daemon_access(self):
        result, calls = self.run_with_endpoint(
            docker_context="production", context_endpoint="ssh://production.example"
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing non-local Docker context endpoint", result.stderr)
        self.assertEqual(calls, [
            "compose version",
            "context show",
            "context inspect production --format {{.Endpoints.docker.Host}}",
        ])

    def test_local_host_does_not_mask_remote_selected_context(self):
        # Both selectors must be safe even when the CLI prioritizes one.
        result, calls = self.run_with_endpoint(
            docker_host="unix:///var/run/docker.sock",
            docker_context="production",
            context_endpoint="ssh://production.example",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing non-local Docker context endpoint", result.stderr)
        self.assertNotIn("info", calls)

    def test_remote_host_is_rejected_even_with_local_context(self):
        result, calls = self.run_with_endpoint(
            docker_host="ssh://production.example",
            docker_context="default",
            context_endpoint="unix:///var/run/docker.sock",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(calls, ["compose version"])

    def test_local_context_reaches_daemon_check(self):
        result, calls = self.run_with_endpoint()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Docker daemon is not running", result.stderr)
        self.assertEqual(calls[-1], "info")


if __name__ == "__main__":
    unittest.main()
