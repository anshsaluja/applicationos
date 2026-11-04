"use client";

import { useState } from "react";

type Requirement = { id: string; title: string; description: string; status: string; evidence: unknown[] };
type Result = { workspace_id: string; requirements: Requirement[] };
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
