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

    def test_compose_environment_overrides_fail_before_docker_access(self):
        # A caller must not redirect verification into a different Compose
        # project, hide or remove orphans, or alter environment-file loading.
        overrides = (
            "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES",
            "COMPOSE_ENV_FILES", "COMPOSE_PATH_SEPARATOR",
            "COMPOSE_CONVERT_WINDOWS_PATHS", "COMPOSE_IGNORE_ORPHANS",
            "COMPOSE_REMOVE_ORPHANS", "COMPOSE_DISABLE_ENV_FILE",
        )
        for name in overrides:
            with self.subTest(override=name), tempfile.TemporaryDirectory() as temp:
                directory = pathlib.Path(temp)
                fake = directory / "docker"
                log = directory / "docker-calls"
                fake.write_text("#!/usr/bin/env bash\n" "touch \"$DOCKER_CALL_LOG\"\n")
                fake.chmod(0o755)
                env = os.environ.copy()
                for key in overrides:
                    env.pop(key, None)
                env.update({
                    "PATH": str(directory) + os.pathsep + env["PATH"],
                    "DOCKER_CALL_LOG": str(log),
                    name: "1",
                })
                result = subprocess.run(
                    ["bash", str(SCRIPT)], cwd=ROOT, env=env,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f"Refusing ambient {name} override", result.stderr)
                self.assertFalse(log.exists(), "Docker accessed before safety preflight")

    def test_remote_docker_host_is_rejected_before_context_or_daemon_access(self):
        for endpoint in ("ssh://build.example", "tcp://127.0.0.1:2375", "https://build.example"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(docker_host=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local DOCKER_HOST", result.stderr)
                self.assertEqual(calls, ["compose version"])

    def test_malformed_local_docker_host_is_rejected_before_daemon_access(self):
        for endpoint in ("unix://", "unix://relative", "npipe://", "npipe://server/pipe/docker_engine"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(docker_host=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local DOCKER_HOST", result.stderr)
                self.assertEqual(calls, ["compose version"])

    def test_malformed_local_context_is_rejected_before_daemon_access(self):
        for endpoint in ("unix://", "unix://relative", "npipe://", "npipe://server/pipe/docker_engine"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(context_endpoint=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local Docker context endpoint", result.stderr)
                self.assertNotIn("info", calls)

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

    def test_missing_or_malformed_context_endpoint_fails_closed(self):
        # A context without a usable local socket must never reach docker info.
        for endpoint in ("", "not-a-docker-endpoint", "unixsocket:///var/run/docker.sock"):
            with self.subTest(endpoint=endpoint):
                result, calls = self.run_with_endpoint(context_endpoint=endpoint)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Refusing non-local Docker context endpoint", result.stderr)
                self.assertNotIn("info", calls)

    def test_remote_host_with_whitespace_cannot_bypass_local_check(self):
        result, calls = self.run_with_endpoint(
            docker_host=" unix:///var/run/docker.sock"
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing non-local DOCKER_HOST", result.stderr)
        self.assertEqual(calls, ["compose version"])

    def test_local_context_reaches_daemon_check(self):
        result, calls = self.run_with_endpoint()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Docker daemon is not running", result.stderr)
        self.assertEqual(calls[-1], "info")


    def test_stopped_compose_services_are_not_reused(self):
        # A stopped project is still developer-owned; 'up' could recreate it.
        with tempfile.TemporaryDirectory() as temp:
            directory = pathlib.Path(temp)
            calls = directory / "calls"
            fake = directory / "docker"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n"
                "case \"$*\" in\n"
                "  'compose version') exit 0 ;;\n"
                "  'context show') echo default ;;\n"
                "  context\\ inspect\\ *\\ --format\\ *) echo unix:///var/run/docker.sock ;;\n"
                "  'info') exit 0 ;;\n"
                "  'compose ps --all --services') echo postgres ;;\n"
                "  *) echo unexpected-operation >&2; exit 99 ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": str(directory) + os.pathsep + env["PATH"],
                "DOCKER_CALL_LOG": str(calls),
                "DOCKER_HOST": "",
            })
            env.pop("DOCKER_CONTEXT", None)
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("Refusing to modify existing Compose services", result.stderr)
            self.assertIn("compose ps --all --services", calls.read_text())
            self.assertNotIn("compose up", calls.read_text())


    def test_orphaned_compose_volume_blocks_startup(self):
        # Containers may be gone while developer-owned named volumes remain.
        with tempfile.TemporaryDirectory() as temp:
            directory = pathlib.Path(temp)
            calls = directory / "calls"
            fake = directory / "docker"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n"
                "case \"$*\" in\n"
                "  'compose version') exit 0 ;;\n"
                "  'context show') echo default ;;\n"
                "  context\ inspect\ *\ --format\ *) echo unix:///var/run/docker.sock ;;\n"
                "  'info') exit 0 ;;\n"
                "  'compose ps --all --services') exit 0 ;;\n"
                "  'compose config --quiet') exit 0 ;;\n"
                "  'compose config --format json') echo '{\"name\":\"applicationos\"}' ;;\n"
                "  volume\ ls\ *) echo applicationos_postgres_data ;;\n"
                "  *) echo unexpected-operation >&2; exit 99 ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": str(directory) + os.pathsep + env["PATH"],
                "DOCKER_CALL_LOG": str(calls),
                "DOCKER_HOST": "",
            })
            env.pop("DOCKER_CONTEXT", None)
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("Refusing to reuse existing Compose volumes", result.stderr)
            self.assertIn("applicationos_postgres_data", result.stderr)
            self.assertIn("volume ls --filter label=com.docker.compose.project=applicationos", calls.read_text())
            self.assertNotIn("compose up", calls.read_text())


if __name__ == "__main__":
    unittest.main()
