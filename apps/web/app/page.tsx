"use client";

import { useState } from "react";

type Requirement = { id: string; title: string; description: string; status: string; evidence: unknown[] };
type Result = { workspace_id: string; requirements: Requirement[] };
type WorkflowCheckpoint = { action_id: string; status: string; attempt: number; max_attempts: number; idempotency_key: string; last_error: string | null };
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try { const body = await response.json(); detail = String(body.detail ?? detail); } catch { /* non-JSON error */ }
    throw new Error(`Request failed (${response.status}): ${detail}`);
  }
  return response.json() as Promise<T>;
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [workspaceLookup, setWorkspaceLookup] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [workflow, setWorkflow] = useState<WorkflowCheckpoint | null>(null);
  const [workflowError, setWorkflowError] = useState("");
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [workflowNotice, setWorkflowNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function processDocument(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const uploaded = await responseJson<{ id: string }>(await fetch(`${API}/v1/documents`, { method: "POST", body }));
      setDocumentId(uploaded.id);
      const persisted = await responseJson<Result>(await fetch(`${API}/v1/documents/${uploaded.id}/requirements/persist`, { method: "POST" }));
      setResult(persisted);
      setWorkspaceLookup(persisted.workspace_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally { setBusy(false); }
  }

  async function loadWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = workspaceLookup.trim();
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) || busy) {
      setError("Enter a valid workspace UUID.");
      return;
    }
    setBusy(true); setError(""); setResult(null); setDocumentId("");
    try {
      const saved = await responseJson<Result>(await fetch(`${API}/v1/workspaces/${encodeURIComponent(id)}/requirements`, { cache: "no-store" }));
      setResult(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load workspace");
    } finally { setBusy(false); }
  }

  async function loadWorkflow(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = workflowId.trim();
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
      setWorkflow(null); setWorkflowError("Enter a valid action UUID."); return;
    }
    if (workflowBusy) return;
    setWorkflowBusy(true); setWorkflowError(""); setWorkflow(null);
    try {
      const saved = await responseJson<WorkflowCheckpoint>(await fetch(`${API}/v1/workflows/${encodeURIComponent(id)}`, { cache: "no-store" }));
      setWorkflow(saved);
    } catch (err) {
      setWorkflowError(err instanceof Error ? err.message : "Unable to load workflow");
    } finally { setWorkflowBusy(false); }
  }

  async function mutateWorkflow(operation: "create" | "request-review") {
    if (workflowBusy) return;
    const id = workflowId.trim();
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
      setWorkflowError("Enter a valid action UUID."); return;
    }
    if (operation === "create" && (!idempotencyKey.trim() || idempotencyKey.length > 200)) {
      setWorkflowError("Enter an idempotency key (1–200 characters)."); return;
    }
    setWorkflowBusy(true); setWorkflowError(""); setWorkflowNotice("");
    try {
      const url = operation === "create" ? `${API}/v1/workflows` : `${API}/v1/workflows/${encodeURIComponent(id)}/request-review`;
      const response = await fetch(url, {
        method: "POST",
        ...(operation === "create" ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action_id: id, idempotency_key: idempotencyKey.trim(), max_attempts: 3 }),
        } : {}),
      });
      const updated = await responseJson<WorkflowCheckpoint>(response);
      setWorkflow(updated);
      setWorkflowNotice(operation === "create" ? "Workflow checkpoint saved. No action has been executed." : "Review requested. An authorized operator must decide before execution.");
    } catch (err) {
      setWorkflowError(err instanceof Error ? err.message : "Unable to update workflow");
    } finally { setWorkflowBusy(false); }
  }

  return (
    <main style={{ maxWidth: 850, margin: "4rem auto", padding: "0 1.5rem", fontFamily: "system-ui", lineHeight: 1.6 }}>
      <h1>ApplicationOS</h1>
      <p>Review application instructions and track extracted requirements. This demo does not verify compliance or submit applications.</p>
      <form onSubmit={processDocument}>
        <label htmlFor="document">Upload application instructions (PDF or UTF-8 text, max 8 MiB)</label>
        <div style={{ margin: "1rem 0" }}>
          <input id="document" type="file" accept=".txt,.pdf,text/plain,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </div>
        <button disabled={!file || busy} type="submit">{busy ? "Processing…" : "Extract and save requirements"}</button>
      </form>
      <form onSubmit={loadWorkspace} style={{ marginTop: "2rem" }}>
        <label htmlFor="workspace">Resume an existing workspace</label>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
          <input id="workspace" aria-label="Workspace UUID" placeholder="Workspace UUID" value={workspaceLookup} onChange={(e) => setWorkspaceLookup(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          <button type="submit" disabled={busy || !workspaceLookup.trim()}>Load saved requirements</button>
        </div>
      </form>
      <section style={{ marginTop: "2rem", borderTop: "1px solid #ddd", paddingTop: "1rem" }}>
        <h2>Workflow checkpoint</h2>
        <p>Inspect durable workflow state by action ID. This read-only view cannot approve or execute actions.</p>
        <form onSubmit={loadWorkflow}>
          <label htmlFor="workflow-id">Action UUID</label>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <input id="workflow-id" value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} placeholder="Action UUID" style={{ flex: 1, minWidth: 0 }} />
            <button type="submit" disabled={workflowBusy || !workflowId.trim()}>{workflowBusy ? "Loading…" : "Check status"}</button>
          </div>
        </form>
        <div style={{ marginTop: "1rem", display: "grid", gap: "0.5rem" }}>
          <label htmlFor="idempotency-key">Idempotency key for new workflow</label>
          <input id="idempotency-key" maxLength={200} value={idempotencyKey} onChange={(e) => setIdempotencyKey(e.target.value)} placeholder="Unique request key" />
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="button" disabled={workflowBusy || !workflowId.trim() || !idempotencyKey.trim()} onClick={() => void mutateWorkflow("create")}>Create checkpoint</button>
            <button type="button" disabled={workflowBusy || workflow?.status !== "pending" || workflow.action_id !== workflowId.trim()} onClick={() => void mutateWorkflow("request-review")}>Request human review</button>
          </div>
          <small>Creation records intent only. Review requests never grant approval or execute external actions.</small>
        </div>
        {workflowNotice && <p role="status">{workflowNotice}</p>}
        {workflowError && <p role="alert" style={{ color: "crimson" }}>{workflowError}</p>}
        {workflow && <div aria-live="polite">
          <p><strong>Status:</strong> {workflow.status.replaceAll("_", " ")}</p>
          <p><strong>Attempts:</strong> {workflow.attempt} / {workflow.max_attempts}</p>
          <p><strong>Idempotency key:</strong> <code style={{ overflowWrap: "anywhere" }}>{workflow.idempotency_key}</code></p>
          {workflow.last_error && <p><strong>Last error:</strong> {workflow.last_error}</p>}
        </div>}
      </section>
      {error && <p role="alert" style={{ color: "crimson" }}>{error}</p>}
      {result && (
        <section aria-live="polite">
          <h2>Saved requirements ({result.requirements.length})</h2>
          <p>Workspace: <code>{result.workspace_id}</code></p>
          {documentId && <p>Source document: <code>{documentId}</code></p>}
          <p>Save this workspace ID to resume reviewing it later.</p>
          {result.requirements.length === 0 && <p>No explicit requirements detected. Review the document manually.</p>}
          <ul>{result.requirements.map((item) => (
            <li key={item.id} style={{ marginBottom: "1rem" }}>
              <strong>{item.title}</strong> — {item.status}
              <div>{item.description}</div>
              <small>Compliance evidence: {item.evidence.length} item(s). No automatic satisfaction claims.</small>
            </li>
          ))}</ul>
        </section>
      )}
    </main>
  );
}
