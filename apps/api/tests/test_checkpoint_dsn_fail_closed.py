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
    with pytest.raises(ValueError, match="database"), durable_planning.postgres_planning_graph(invalid_dsn):
        pass


def test_checkpoint_dsn_keeps_escaped_password_and_database_name():
    """Do not silently decode or discard credentials or an encoded DB name."""
    dsn = "postgresql+psycopg://user:p%40ss%2Fword@localhost:5432/workflows?sslmode=require"
    assert durable_planning.checkpoint_dsn(dsn) == (
        "postgresql://user:p%40ss%2Fword@localhost:5432/workflows?sslmode=require"
    )


@pytest.mark.parametrize(
    "invalid_dsn",
    [
        "sqlite:///tmp/checkpoints.db",
        "mysql://localhost/workflows",
        "postgresql+asyncpg://localhost/workflows",
        "not-a-url",
        "",
        "   ",
    ],
)
def test_checkpoint_dsn_rejects_unsupported_or_malformed_urls(invalid_dsn):
    """Do not accidentally initialize checkpoints through another driver."""
    with pytest.raises(ValueError, match="PostgreSQL|Invalid"):
        durable_planning.checkpoint_dsn(invalid_dsn)


def test_checkpoint_dsn_preserves_encoded_database_and_connection_options():
    """Connection identity and TLS parameters must survive driver normalization."""
    dsn = (
        "postgresql+psycopg://reviewer:p%40ss@localhost:5432/"
        "application%2Dos?sslmode=verify-full&connect_timeout=5"
    )
    assert durable_planning.checkpoint_dsn(dsn) == (
        "postgresql://reviewer:p%40ss@localhost:5432/"
        "application%2Dos?connect_timeout=5&sslmode=verify-full"
    )


@pytest.mark.parametrize("invalid_dsn", [None, 123, b"postgresql://localhost/workflows", {}, []])
def test_checkpoint_dsn_rejects_non_string_values_before_connection(monkeypatch, invalid_dsn):
    """Configuration mistakes must not reach the PostgreSQL saver."""
    def unexpected_connection(dsn):
        pytest.fail(f"Opened saver for invalid checkpoint DSN: {dsn!r}")

    monkeypatch.setattr(
        durable_planning.PostgresSaver, "from_conn_string", unexpected_connection
    )
    with pytest.raises(TypeError, match="must be a string"), durable_planning.postgres_planning_graph(invalid_dsn):
        pass
