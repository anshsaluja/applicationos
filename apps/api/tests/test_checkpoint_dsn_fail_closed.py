"""Fail-closed PostgreSQL checkpoint DSN regression coverage."""
import pytest

from app import durable_planning


@pytest.mark.parametrize(
    "invalid_dsn",
    [
        "postgresql://localhost",
        "postgresql://localhost/",
        "postgresql+psycopg://localhost/",
        "postgresql://localhost/%20",
        "postgresql://localhost/   ",
    ],
)
def test_invalid_checkpoint_database_never_opens_connection(monkeypatch, invalid_dsn):
    """A missing or whitespace-only database must fail before opening a saver."""
    def unexpected_connection(dsn):
        pytest.fail(f"Opened saver for invalid checkpoint DSN: {dsn}")

    monkeypatch.setattr(
        durable_planning.PostgresSaver, "from_conn_string", unexpected_connection
    )
    with pytest.raises(ValueError, match="database"):
        with durable_planning.postgres_planning_graph(invalid_dsn):
            pass


def test_checkpoint_dsn_keeps_escaped_password_and_database_name():
    """Do not silently decode or discard credentials or an encoded DB name."""
    dsn = "postgresql+psycopg://user:p%40ss%2Fword@localhost:5432/workflows?sslmode=require"
    assert durable_planning.checkpoint_dsn(dsn) == (
        "postgresql://user:p%40ss%2Fword@localhost:5432/workflows?sslmode=require"
    )
