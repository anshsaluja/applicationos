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
