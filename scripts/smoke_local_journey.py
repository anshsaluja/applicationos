#!/usr/bin/env python3
"""Local-only ApplicationOS HTTP + PostgreSQL journey smoke test.

Requires the Compose API and database to be running. Uses synthetic instructions
and never approves or dispatches an action.
"""
import hashlib
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


# Validate the execution database before creating or approving any workflow.
# A remote DATABASE_URL must never receive synthetic smoke-test writes.
if os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
    from sqlalchemy.engine import make_url

    database_url = os.getenv("DATABASE_URL", "")
    try:
        parsed_db = make_url(database_url)
    except Exception as exc:
        raise SystemExit("Synthetic execution requires a valid local PostgreSQL URL") from exc
    if (
        parsed_db.drivername != "postgresql+psycopg"
        or parsed_db.host not in {"localhost", "127.0.0.1", "::1", "postgres"}
        or any(k.lower() in {"host", "hostaddr", "service"} for k in parsed_db.query)
    ):
        raise SystemExit("Synthetic smoke execution requires explicitly local PostgreSQL")
    if not os.getenv("APPLICATIONOS_SMOKE_REVIEW_TOKEN"):
        raise SystemExit("Synthetic execution requires a disposable review token")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow server-controlled redirects outside the local API."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


# Never inherit HTTP(S)_PROXY from the host: even loopback-only smoke traffic
# must reach the local API directly, not a configured proxy.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def request(method, path, body=None, content_type="application/json", extra_headers=None):
    headers = {}
    if body is not None:
        headers["Content-Type"] = content_type
    headers.update(extra_headers or {})
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
    assert document["id"]
    assert document["sha256"] == hashlib.sha256(synthetic).hexdigest(), "Uploaded bytes digest mismatch"
    # Re-ingesting identical bytes must preserve the original document identity and provenance.
    duplicate = request("POST", "/v1/documents", payload, f"multipart/form-data; boundary={boundary}")
    assert duplicate["id"] == document["id"], "Duplicate upload created another document"
    assert duplicate["sha256"] == document["sha256"], "Duplicate upload changed content digest"
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
    # Counts alone can pass when the wrong requirements were persisted. Verify
    # exact identity and document provenance across repeat ingestion/persistence.
    source_ids = {str(item["requirement_id"]) for item in sources}
    first_ids = {str(item["id"]) for item in persisted["requirements"]}
    repeat_ids = {str(item["id"]) for item in again["requirements"]}
    stored_ids = {str(item["id"]) for item in stored["requirements"]}
    assert source_ids, "No source-linked requirements were persisted"
    assert source_ids == first_ids == repeat_ids == stored_ids, (
        "Requirement identities or document provenance changed on replay"
    )
    assert len(source_ids) == len(sources), "Duplicate source requirement identities"
    assert len(first_ids) == len(persisted["requirements"]), (
        "Duplicate persisted requirement identities"
    )
    for item in sources:
        assert not item["satisfaction_evidence"], (
            "Instruction source incorrectly treated as satisfaction evidence"
        )
    action_id = str(uuid4())
    workflow = request("POST", "/v1/workflows", json.dumps({
        "action_id": action_id, "idempotency_key": "smoke-" + action_id
    }).encode())
    assert workflow["action_id"] == action_id
    # Repeating the same intent must reuse the durable checkpoint.
    replay = request("POST", "/v1/workflows", json.dumps({
        "action_id": action_id, "idempotency_key": "smoke-" + action_id
    }).encode())
    assert replay["action_id"] == action_id
    assert replay["idempotency_key"] == workflow["idempotency_key"]
    assert replay["status"] == "pending"
    # Reusing an idempotency key for a different action must fail closed.
    try:
        request("POST", "/v1/workflows", json.dumps({
            "action_id": str(uuid4()), "idempotency_key": "smoke-" + action_id
        }).encode())
    except urllib.error.HTTPError as exc:
        assert exc.code == 409, f"Conflicting idempotency key returned {exc.code}"
    else:
        raise AssertionError("Conflicting idempotency key was accepted")
    review = request("POST", "/v1/workflows/" + action_id + "/request-review", b"{}")
    assert review["status"] == "awaiting_approval"
    assert request("GET", "/v1/workflows/" + action_id)["status"] == "awaiting_approval"
    # Opt-in approval path: require BOTH a disposable reviewer token and explicit local-only mode.
    # An ambient reviewer token alone must never authorize smoke-test decisions.
    token = os.getenv("APPLICATIONOS_SMOKE_REVIEW_TOKEN", "")
    # Every smoke invocation, including the post-restart no-opt-in journey,
    # must prove that a forged reviewer credential cannot authorize an action.
    # This is intentionally checked before the optional synthetic execution path.
    forged_body = json.dumps({"decision": "approved", "reason": "Forged reviewer"}).encode()
    try:
        request(
            "POST", "/v1/workflows/" + action_id + "/decision", forged_body,
            extra_headers={"X-Review-Token": "invalid-synthetic-review-token"},
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == 403, f"Forged reviewer token returned {exc.code}, expected 403"
    else:
        raise AssertionError("Forged reviewer credential approved a workflow")
    assert request("GET", "/v1/workflows/" + action_id)["status"] == "awaiting_approval", (
        "Forged reviewer request mutated the pending approval state"
    )
    if os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only" and not token:
        raise AssertionError("Synthetic execution was requested without an approval test token")
    if token and os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
        decision_path = "/v1/workflows/" + action_id + "/decision"
        decision_body = json.dumps({"decision": "approved", "reason": "Synthetic CI review"}).encode()
        try:
            request("POST", decision_path, decision_body)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, f"Unauthenticated approval returned {exc.code}, expected 403"
        else:
            raise AssertionError("Unauthenticated approval unexpectedly succeeded")
        approved = request("POST", decision_path, decision_body, extra_headers={"X-Review-Token": token})
        assert approved["status"] == "ready", "Approved workflow did not become ready"
        assert request("GET", "/v1/workflows/" + action_id)["status"] == "ready"
        # A signed decision is single-use: a replay must not overwrite the
        # approval record or change an already-approved workflow.
        try:
            request("POST", decision_path, decision_body, extra_headers={"X-Review-Token": token})
        except urllib.error.HTTPError as exc:
            assert exc.code == 409, f"Approval replay returned {exc.code}, expected 409"
        else:
            raise AssertionError("Approval replay unexpectedly succeeded")
        assert request("GET", "/v1/workflows/" + action_id)["status"] == "ready"

        # Exercise rejection independently, using a second synthetic action.
        rejected_action_id = str(uuid4())
        rejected_workflow = request("POST", "/v1/workflows", json.dumps({
            "action_id": rejected_action_id,
            "idempotency_key": "smoke-reject-" + rejected_action_id,
        }).encode())
        assert rejected_workflow["status"] == "pending"
        rejected_review = request(
            "POST", "/v1/workflows/" + rejected_action_id + "/request-review", b"{}"
        )
        assert rejected_review["status"] == "awaiting_approval"
        rejected = request(
            "POST", "/v1/workflows/" + rejected_action_id + "/decision",
            json.dumps({"decision": "rejected", "reason": "Synthetic rejection test"}).encode(),
            extra_headers={"X-Review-Token": token},
        )
        assert rejected["status"] == "failed"
        assert request("GET", "/v1/workflows/" + rejected_action_id)["status"] == "failed"
        # Rejected workflows cannot be reset into review.
        try:
            request("POST", "/v1/workflows/" + rejected_action_id + "/request-review", b"{}")
        except urllib.error.HTTPError as exc:
            assert exc.code == 409, f"Rejected workflow reset returned {exc.code}, expected 409"
        else:
            raise AssertionError("Rejected workflow was reset to review")
        boundary_result = "approved and rejected synthetic decisions, stopped before execution"
        # Optional disposable-database execution path. Never run without both
        # a local reviewer credential and an explicit synthetic-only opt-in.
        if os.getenv("APPLICATIONOS_SMOKE_SYNTHETIC_EXECUTION") == "local-only":
            from app.persistence import (
                SyntheticReceiptRow, WorkflowOutboxRepository, WorkflowRepository,
                build_session_factory,
            )
            from app.synthetic_worker import dispatch_one_synthetic

            factory = build_session_factory(database_url)
            with factory.begin() as session:
                repository = WorkflowRepository(session)
                claimed = repository.claim_ready(__import__("uuid").UUID(action_id))
                assert claimed.status.value == "running"
                WorkflowOutboxRepository(session).enqueue_claimed(claimed.action_id)
            receipt = dispatch_one_synthetic(factory, action_id=__import__("uuid").UUID(action_id))
            assert receipt is not None and receipt.action_id == __import__("uuid").UUID(action_id)
            assert dispatch_one_synthetic(factory, action_id=receipt.action_id) is None
            with factory.begin() as session:
                original_receipt = session.get(SyntheticReceiptRow, receipt.action_id)
                assert original_receipt is not None, "Synthetic completion has no durable receipt"
                receipt_action_id = original_receipt.action_id
            completed = request("GET", "/v1/workflows/" + action_id)
            assert completed["status"] == "succeeded"
            assert completed["idempotency_key"] == "smoke-" + action_id
            # An HTTP retry after completion must resolve to the original
            # terminal checkpoint rather than schedule a second action.
            completed_replay = request("POST", "/v1/workflows", json.dumps({
                "action_id": action_id, "idempotency_key": "smoke-" + action_id
            }).encode())
            assert completed_replay["action_id"] == action_id
            assert completed_replay["status"] == "succeeded", "Completion was lost on replay"
            assert completed_replay["idempotency_key"] == completed["idempotency_key"]
            assert completed_replay == completed, "Replay mutated the terminal checkpoint"
            assert dispatch_one_synthetic(factory, action_id=receipt.action_id) is None
            with factory.begin() as session:
                replay_receipt = session.get(SyntheticReceiptRow, receipt.action_id)
                assert replay_receipt is not None, "Replay removed the synthetic receipt"
                assert replay_receipt.action_id == receipt_action_id, "Replay changed receipt identity"
            # Rejected actions must never acquire a receipt, even if explicitly dispatched.
            rejected_uuid = __import__("uuid").UUID(rejected_action_id)
            assert dispatch_one_synthetic(factory, action_id=rejected_uuid) is None
            with factory.begin() as session:
                assert session.get(SyntheticReceiptRow, rejected_uuid) is None, (
                    "Rejected workflow acquired a synthetic execution receipt"
                )
                persisted_receipt = session.get(SyntheticReceiptRow, receipt.action_id)
                assert persisted_receipt is not None
                assert persisted_receipt.action_id == receipt_action_id
            assert request("GET", "/v1/workflows/" + rejected_action_id)["status"] == "failed"
            boundary_result = "approved synthetic no-op completed once; rejected action never dispatched"
    else:
        boundary_result = "stopped before approval or execution"
    print(json.dumps({
        "result": "PASS", "document_id": document["id"],
        "document_sha256": hashlib.sha256(synthetic).hexdigest(),
        "requirement_count": len(stored["requirements"]),
        "workspace_id": stored["workspace_id"], "workflow_id": action_id,
        "boundary": boundary_result
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, urllib.error.URLError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
