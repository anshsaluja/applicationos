"""Readiness is distinct from liveness and never leaks database errors."""

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_readiness_reports_database_failure_without_leaking_details(monkeypatch):
    def broken_engine():
        raise RuntimeError("sensitive connection string")

    monkeypatch.setattr(main, "build_engine", broken_engine)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "sensitive" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/health").status_code == 200


def test_readiness_checks_database_and_disposes_engine(monkeypatch):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement):
            calls.append(str(statement))
            return 1

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            calls.append("disposed")

    monkeypatch.setattr(main, "build_engine", Engine)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert calls == ["SELECT 1", "disposed"]
