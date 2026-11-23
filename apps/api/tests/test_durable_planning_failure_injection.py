"""Failure-injection tests for durable planner initialization and cleanup."""

from contextlib import contextmanager

import pytest

from app import durable_planning


def test_failed_checkpoint_setup_closes_connection_without_compiling(monkeypatch):
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield FakeSaver()
            finally:
                events.append("close")

        def setup(self):
            events.append("setup")
            raise RuntimeError("migration unavailable")

    def compile_graph(*, checkpointer):
        events.append("compile")
        return object()

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", compile_graph)

    with (
        pytest.raises(RuntimeError, match="migration unavailable"),
        durable_planning.postgres_planning_graph(
            "postgresql://localhost/test", initialize=True
        ),
    ):
        pass

    assert events == ["open", "setup", "close"]


def test_checkpoint_connection_closes_on_generator_early_exit(monkeypatch):
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield object()
            finally:
                events.append("close")

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(
        durable_planning, "build_planning_graph", lambda **kwargs: object()
    )

    with durable_planning.postgres_planning_graph(
        "postgresql://localhost/test"
    ) as graph:
        assert graph is not None

    assert events == ["open", "close"]



def test_graph_compilation_failure_closes_checkpoint_connection(monkeypatch):
    """A failed graph build must never leave a saver connection open."""
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield FakeSaver()
            finally:
                events.append("close")

        def setup(self):
            events.append("setup")

    def fail_compile(*, checkpointer):
        events.append("compile")
        raise RuntimeError("graph compilation failed")

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", fail_compile)

    with (
        pytest.raises(RuntimeError, match="graph compilation failed"),
        durable_planning.postgres_planning_graph(
            "postgresql://localhost/test", initialize=True
        ),
    ):
        pass

    assert events == ["open", "setup", "compile", "close"]


def test_existing_checkpoint_graph_does_not_rerun_schema_setup(monkeypatch):
    """Opening a graph for a request must not run schema migrations."""
    events = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append("open")
            try:
                yield FakeSaver()
            finally:
                events.append("close")

        def setup(self):
            pytest.fail("Request-time checkpoint opening attempted schema migration")

    def compile_graph(*, checkpointer):
        events.append("compile")
        return object()

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", compile_graph)

    with durable_planning.postgres_planning_graph("postgresql://localhost/test"):
        events.append("use")

    assert events == ["open", "compile", "use", "close"]


def test_runtime_failure_closes_saver_and_reopen_uses_same_dsn(monkeypatch):
    """A failed planning request must release its connection for recovery."""
    events = []
    compiled = []

    class FakeSaver:
        @staticmethod
        @contextmanager
        def from_conn_string(dsn):
            events.append(("open", dsn))
            saver = object()
            try:
                yield saver
            finally:
                events.append(("close", dsn))

    def compile_graph(*, checkpointer):
        compiled.append(checkpointer)
        return object()

    monkeypatch.setattr(durable_planning, "PostgresSaver", FakeSaver)
    monkeypatch.setattr(durable_planning, "build_planning_graph", compile_graph)
    dsn = "postgresql+psycopg://localhost/applicationos"
    normalized = "postgresql://localhost/applicationos"

    with pytest.raises(RuntimeError, match="interrupted"):
        with durable_planning.postgres_planning_graph(dsn):
            raise RuntimeError("interrupted")

    with durable_planning.postgres_planning_graph(dsn) as recovered:
        assert recovered is not None

    assert events == [
        ("open", normalized),
        ("close", normalized),
        ("open", normalized),
        ("close", normalized),
    ]
    assert len(compiled) == 2
    assert compiled[0] is not compiled[1]
