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
