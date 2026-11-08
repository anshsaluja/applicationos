#!/usr/bin/env python3
"""Local-only ApplicationOS HTTP + PostgreSQL journey smoke test.

Requires the Compose API and database to be running. Uses synthetic instructions
and never approves or dispatches an action.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

BASE = os.getenv("APPLICATIONOS_SMOKE_API_URL", "http://127.0.0.1:8000").rstrip("/")
target = urllib.parse.urlsplit(BASE)
if (
    target.scheme != "http"
    or target.hostname not in {"127.0.0.1", "localhost", "::1"}
    or target.username is not None
    or target.password is not None
    or target.path not in {"", "/"}
    or target.query
    or target.fragment
):
    raise SystemExit("Refusing unsafe or non-local smoke test target")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow server-controlled redirects outside the local API."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


opener = urllib.request.build_opener(NoRedirect)


def request(method, path, body=None, content_type="application/json"):
    headers = {}
    if body is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with opener.open(req, timeout=15) as response:
        return json.load(response)


def main():
    assert request("GET", "/health")["status"] == "ok"
    boundary = "applicationos-smoke-" + uuid4().hex
    synthetic = (
        b"Please provide proof of income.\n"
        b"Please submit a government-issued photo ID.\n"
        b"Please provide rental history.\n"
    )
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="synthetic-instructions.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + synthetic + f"\r\n--{boundary}--\r\n".encode()
    document = request("POST", "/v1/documents", payload, f"multipart/form-data; boundary={boundary}")
    assert document["id"] and document["sha256"]
    fetched = request("GET", "/v1/documents/" + document["id"])
    assert fetched["sha256"] == document["sha256"]
    sources = request("GET", "/v1/documents/" + document["id"] + "/requirement-sources")
    assert sources, "Synthetic instructions produced no requirement candidates"
    assert all(s["source_document_id"] == document["id"] for s in sources)
    assert all(not s["satisfaction_evidence"] for s in sources)
    persisted = request("POST", "/v1/documents/" + document["id"] + "/requirements/persist", b"{}")
    again = request("POST", "/v1/documents/" + document["id"] + "/requirements/persist", b"{}")
    assert persisted["workspace_id"] == again["workspace_id"]
    assert len(persisted["requirements"]) == len(again["requirements"])
    stored = request("GET", "/v1/workspaces/" + persisted["workspace_id"] + "/requirements")
    assert len(stored["requirements"]) == len(persisted["requirements"])
    action_id = str(uuid4())
    workflow = request("POST", "/v1/workflows", json.dumps({
        "action_id": action_id, "idempotency_key": "smoke-" + action_id
    }).encode())
    assert workflow["action_id"] == action_id
    review = request("POST", "/v1/workflows/" + action_id + "/request-review", b"{}")
    assert review["status"] == "awaiting_approval"
    assert request("GET", "/v1/workflows/" + action_id)["status"] == "awaiting_approval"
    print(json.dumps({
        "result": "PASS", "document_id": document["id"],
        "requirement_count": len(stored["requirements"]),
        "workspace_id": stored["workspace_id"], "workflow_id": action_id,
        "boundary": "stopped before approval or execution"
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
