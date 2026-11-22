"""Regression coverage for persisted workspace isolation.

These tests use the real API and disposable PostgreSQL configured by CI.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_persisted_requirements_never_leak_between_workspaces() -> None:
    with TestClient(app) as client:
        first_upload = client.post(
            "/v1/documents",
            files={"file": ("first-workspace.txt", b"You must submit a passport.", "text/plain")},
        )
        second_upload = client.post(
            "/v1/documents",
            files={"file": ("second-workspace.txt", b"You must provide a bank statement.", "text/plain")},
        )
        assert first_upload.status_code == second_upload.status_code == 200
        assert first_upload.json()["id"] != second_upload.json()["id"]

        first = client.post(
            f'/v1/documents/{first_upload.json()["id"]}/requirements/persist'
        )
        second = client.post(
            f'/v1/documents/{second_upload.json()["id"]}/requirements/persist'
        )
        assert first.status_code == second.status_code == 200
        first_workspace = first.json()["workspace_id"]
        second_workspace = second.json()["workspace_id"]
        assert first_workspace != second_workspace

        first_read = client.get(f"/v1/workspaces/{first_workspace}/requirements")
        second_read = client.get(f"/v1/workspaces/{second_workspace}/requirements")
        assert first_read.status_code == second_read.status_code == 200
        assert first_read.json() == first.json()
        assert second_read.json() == second.json()

        first_requirements = first_read.json()["requirements"]
        second_requirements = second_read.json()["requirements"]
        assert len(first_requirements) == len(second_requirements) == 1
        assert first_requirements[0]["id"] != second_requirements[0]["id"]
        assert "passport" in first_requirements[0]["description"].lower()
        assert "bank statement" in second_requirements[0]["description"].lower()
        assert "bank statement" not in first_requirements[0]["description"].lower()
        assert "passport" not in second_requirements[0]["description"].lower()
