"""Safety and bounded-execution checks for the local synthetic worker CLI."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import pytest

from app import synthetic_cli


def test_cli_rejects_missing_opt_in(monkeypatch):
    monkeypatch.delenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    with pytest.raises(SystemExit) as error:
        synthetic_cli.main([])
    assert error.value.code == 2


@pytest.mark.parametrize("host", ["db.example.com", "neon.tech", "10.0.0.5"])
def test_cli_rejects_remote_database(monkeypatch, host):
    monkeypatch.setenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER", "local-only")
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://u:p@{host}/db")
    with pytest.raises(SystemExit) as error:
        synthetic_cli.main([])
    assert error.value.code == 2


@pytest.mark.parametrize("count", ["0", "101", "-1"])
def test_cli_rejects_invalid_batch_size(monkeypatch, count):
    with pytest.raises(SystemExit) as error:
        synthetic_cli.main(["--max-actions", count])
    assert error.value.code == 2


def test_cli_dispatches_at_most_requested_count(monkeypatch, capsys):
    monkeypatch.setenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER", "local-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    factory = Mock()
    monkeypatch.setattr(synthetic_cli, "build_session_factory", lambda url: factory)
    receipt = Mock(action_id=uuid4(), adapter="synthetic-noop")
    dispatch = Mock(side_effect=[receipt, None])
    monkeypatch.setattr(synthetic_cli, "dispatch_one_synthetic", dispatch)
    assert synthetic_cli.main(["--max-actions", "3"]) == 0
    assert dispatch.call_count == 2
    assert "synthetic actions completed: 1" in capsys.readouterr().out


def test_cli_action_id_is_forwarded(monkeypatch):
    monkeypatch.setenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER", "local-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1/db")
    monkeypatch.setattr(synthetic_cli, "build_session_factory", lambda url: Mock())
    dispatch = Mock(return_value=None)
    monkeypatch.setattr(synthetic_cli, "dispatch_one_synthetic", dispatch)
    action_id = uuid4()
    assert synthetic_cli.main(["--action-id", str(action_id)]) == 0
    assert dispatch.call_args.kwargs["action_id"] == action_id


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:invalid/db",
        "postgresql+psycopg://u:p@localhost/db?host=remote.example.com",
        "postgresql+psycopg://u:p@localhost/db?hostaddr=10.0.0.1",
        "postgresql+psycopg://u:p@localhost/db?service=production",
    ],
)
def test_cli_rejects_invalid_or_overridden_database_targets(monkeypatch, url):
    monkeypatch.setenv("APPLICATIONOS_ENABLE_SYNTHETIC_WORKER", "local-only")
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(SystemExit) as error:
        synthetic_cli.main([])
    assert error.value.code == 2
