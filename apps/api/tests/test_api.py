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


def test_requirement_evaluation_rejects_oversized_batches_before_processing() -> None:
    """Bound CPU and response size for untrusted requirement evaluation input."""
    item = {"title": "ID", "description": "Provide identification", "evidence": []}
    response = client.post(
        "/v1/requirements/evaluate",
        json={"requirements": [item] * 101},
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_requirement_evaluation_accepts_maximum_batch() -> None:
    item = {"title": "ID", "description": "Provide identification", "evidence": []}
    response = client.post(
        "/v1/requirements/evaluate",
        json={"requirements": [item] * 100},
    )
    assert response.status_code == 200
    assert len(response.json()["requirements"]) == 100


def test_cors_origin_configuration_rejects_wildcards_paths_and_credentials() -> None:
    import pytest

    from app.main import parse_cors_origins

    for unsafe in (
        "*",
        "https://*.example.com",
        "https://example.com/path",
        "https://example.com?debug=true",
        "https://user:password@example.com",
        "file:///tmp",
        "https://example.com:99999",
        "https://example.com:0",
    ):
        with pytest.raises(ValueError):
            parse_cors_origins(unsafe)


def test_cors_origin_configuration_normalizes_and_deduplicates() -> None:
    from app.main import parse_cors_origins

    assert parse_cors_origins(
        " https://example.com/, http://localhost:3000, https://example.com "
    ) == ["https://example.com", "http://localhost:3000"]


def test_cors_preflight_only_allows_configured_origin() -> None:
    allowed = client.options(
        "/v1/requirements/evaluate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"

    denied = client.options(
        "/v1/requirements/evaluate",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_workflow_idempotency_key_rejects_ambiguous_input_without_database() -> None:
    from uuid import uuid4

    for key in (" ", "  key", "key ", "key\nother", "key\tother", "key\u007fother"):
        response = client.post(
            "/v1/workflows",
            json={"action_id": str(uuid4()), "idempotency_key": key},
        )
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"


def test_workflow_idempotency_key_preserves_valid_internal_spaces() -> None:
    from uuid import uuid4

    from app.api import WorkflowCreateRequest

    key = "case 123: step 2"
    payload = WorkflowCreateRequest(action_id=uuid4(), idempotency_key=key)
    assert payload.idempotency_key == key


def test_dispatch_reconciliation_flags_inconsistent_persisted_state() -> None:
    """Never report a succeeded workflow as safe without its durable receipt."""
    from app.api import requires_dispatch_reconciliation

    for workflow, outbox, receipt in (
        ("succeeded", None, False),
        ("succeeded", "pending", False),
        ("succeeded", "dispatched", False),
        ("running", None, False),
        ("running", "claimed", False),
        ("failed", "dispatched", True),
        ("ready", "dispatched", True),
        ("running", "quarantined", False),
    ):
        assert requires_dispatch_reconciliation(workflow, outbox, receipt)


def test_dispatch_reconciliation_allows_consistent_checkpoints() -> None:
    from app.api import requires_dispatch_reconciliation

    for workflow, outbox, receipt in (
        ("pending", None, False),
        ("awaiting_approval", None, False),
        ("ready", None, False),
        ("running", "pending", False),
        ("running", "dispatched", True),
        ("succeeded", "dispatched", True),
        ("failed", None, False),
    ):
        assert not requires_dispatch_reconciliation(workflow, outbox, receipt)


def test_dispatch_reconciliation_quarantines_invalid_receipts_even_when_pending() -> None:
    """A receipt with the wrong adapter or idempotency key is suspicious state."""
    from app.api import requires_dispatch_reconciliation

    for workflow, outbox in (
        ("pending", None),
        ("ready", None),
        ("running", "pending"),
        ("running", "dispatched"),
        ("succeeded", "dispatched"),
        ("failed", "quarantined"),
    ):
        assert requires_dispatch_reconciliation(
            workflow, outbox, False, receipt_present=True
        )


def test_dispatch_reconciliation_preserves_absent_receipt_semantics() -> None:
    from app.api import requires_dispatch_reconciliation

    assert not requires_dispatch_reconciliation(
        "running", "pending", False, receipt_present=False
    )
    assert not requires_dispatch_reconciliation(
        "pending", None, False, receipt_present=False
    )
