"""Durable checkpoint wiring must be explicit and fail closed."""
from contextlib import contextmanager
from uuid import uuid4

import pytest

from app import durable_planning


def test_checkpoint_config_uses_stable_action_identity():
    action_id = uuid4()
    assert durable_planning.checkpoint_config(action_id) == {
        "configurable": {"thread_id": str(action_id)}
    }


@pytest.mark.parametrize("identifier", ["", "  "])
def test_checkpoint_config_rejects_missing_identity(identifier):
    with pytest.raises(ValueError, match="thread_id"):
        durable_planning.checkpoint_config(identifier)


def test_checkpoint_connection_is_closed_and_setup_is_opt_in(monkeypatch):
    events = []
    saver = object()

    @contextmanager
    def fake_connection(dsn):
        events.append(("open", dsn))
        try:
            yield saver
        finally:
            events.append(("close", dsn))

    class FakeSaver:
        @staticmethod
        def from_conn_string(dsn):
            return fake_connection(dsn)

    def fake_graph(*, checkpointer):
        assert checkpointer is saver
        return "compiled-graph"

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", fake_graph)

    with durable_planning.postgres_planning_graph("postgresql://localhost/test") as graph:
        assert graph == "compiled-graph"
    assert events == [
        ("open", "postgresql://localhost/test"),
        ("close", "postgresql://localhost/test"),
    ]


def test_checkpoint_setup_only_when_explicitly_requested(monkeypatch):
    events = []

    class FakeSaver:
        @classmethod
        @contextmanager
        def from_conn_string(cls, dsn):
            yield cls()

        def setup(self):
            events.append("setup")

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", lambda **kwargs: object())

    with durable_planning.postgres_planning_graph("postgresql://localhost/test"):
        pass
    assert events == []
    with durable_planning.postgres_planning_graph(
        "postgresql://localhost/test", initialize=True
    ):
        pass
    assert events == ["setup"]


def test_checkpoint_dsn_is_required():
    with pytest.raises(ValueError, match="DSN"):
        with durable_planning.postgres_planning_graph(" "):
            pass
