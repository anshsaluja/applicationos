from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_evaluate_requirement() -> None:
    response = client.post(
        "/v1/requirements/evaluate",
        json={
            "requirements": [
                {
                    "title": "Government ID",
                    "description": "Provide a valid government-issued ID",
                    "evidence": [],
                }
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["missing_count"] == 1
    assert body["requirements"][0]["status"] == "missing"


def test_api_responses_disallow_caching_embedding_and_referrer_leakage() -> None:
    response = client.post("/v1/requirements/evaluate", json={"requirements": []})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_api_error_responses_keep_security_headers() -> None:
    response = client.get("/v1/documents/not-a-uuid")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


def test_request_ids_are_unique_and_not_client_controlled() -> None:
    first = client.get("/health", headers={"X-Request-ID": "attacker-controlled"})
    second = client.get("/health")
    from uuid import UUID

    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]
    assert str(UUID(first_id)) == first_id
    assert str(UUID(second_id)) == second_id
    assert first_id != second_id
    assert first_id != "attacker-controlled"


def test_validation_errors_have_request_ids() -> None:
    response = client.get("/v1/documents/not-a-uuid")
    from uuid import UUID

    assert response.status_code == 422
    assert str(UUID(response.headers["x-request-id"])) == response.headers["x-request-id"]


def test_review_decision_fails_closed_without_operator_configuration(monkeypatch) -> None:
    """No workflow lookup or state mutation is allowed without an operator gate."""
    from uuid import uuid4

    monkeypatch.delenv("APPLICATIONOS_REVIEW_TOKEN", raising=False)
    monkeypatch.delenv("APPLICATIONOS_REVIEWER_ID", raising=False)
    action_id = uuid4()
    for decision in ("approved", "rejected"):
        response = client.post(
            f"/v1/workflows/{action_id}/decision",
            json={"decision": decision},
            headers={"X-Review-Token": "untrusted"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Review authorization unavailable or denied"
        assert response.headers["cache-control"] == "no-store"


def test_review_decision_rejects_incorrect_token_before_database_access(monkeypatch) -> None:
    """Wrong credentials cannot learn whether a workflow exists."""
    from uuid import uuid4

    monkeypatch.setenv("APPLICATIONOS_REVIEW_TOKEN", "local-test-secret")
    monkeypatch.setenv("APPLICATIONOS_REVIEWER_ID", "local-reviewer")
    response = client.post(
        f"/v1/workflows/{uuid4()}/decision",
        json={"decision": "approved"},
        headers={"X-Review-Token": "wrong-secret"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Review authorization unavailable or denied"
