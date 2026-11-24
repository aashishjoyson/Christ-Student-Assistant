import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AdminError, getExperiments, getIngestion, getMonitoring, syncDriveNow,
  type Experiments, type IngestionStatus, type ModeMetrics, type MonitoringReport,
} from "../api/admin";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 1000) / 10}%`);
const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ms`);
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `$${v < 0.01 ? v.toFixed(5) : v.toFixed(3)}`);
const age = (seconds: number | null) => {
  if (seconds === null) return "never";
  if (seconds < 90) return `${seconds} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
};

function Tile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "bad" | "warn" }) {
  return (
    <div className={`tile ${tone ?? ""}`}>
      <span className="tile-label">{label}</span>
      <strong>{value}</strong>
      {note && <span className="tile-note">{note}</span>}
    </div>
  );
}

function EvalRow({ id, note, m }: { id: string; note: string; m: ModeMetrics | undefined }) {
  return (
    <tr>
      <td><code>{id}</code><div className="muted">{note}</div></td>
      <td>{pct(m?.answer_accuracy)}<div className="muted">{m?.n ?? "?"} questions</div></td><td>{pct(m?.context_recall)}</td><td>{pct(m?.citation_hit_rate)}</td>
      <td>{pct(m?.correct_refusal_rate)}</td><td>{ms(m?.latency_p95_ms)}</td><td>{usd(m?.cost_usd_total)}</td>
    </tr>
  );
}

export function AdminPage() {
  const [key, setKey] = useState("");
  const [authed, setAuthed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringReport | null>(null);
  const [ingestion, setIngestion] = useState<IngestionStatus | null>(null);
  const [experiments, setExperiments] = useState<Experiments | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const refresh = useCallback(async (adminKey: string) => {
    try {
      const [m, i, e] = await Promise.all([getMonitoring(adminKey), getIngestion(adminKey), getExperiments(adminKey)]);
      setMonitoring(m); setIngestion(i); setExperiments(e); setAuthed(true); setError(null);
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) setAuthed(false);
      setError(err instanceof Error ? err.message : "Could not reach the API.");
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    const timer = setInterval(() => void refresh(key), 30_000);
    return () => clearInterval(timer);
  }, [authed, key, refresh]);

  async function signIn(e: FormEvent) {
    e.preventDefault();
    await refresh(key.trim());
  }

  async function sync() {
    setSyncing(true); setSyncNote(null);
    try {
      const r = await syncDriveNow(key);
      setSyncNote(`Sync ${r.status}: ${r.files_indexed} indexed, ${r.files_skipped} unchanged, ${r.files_failed} failed${r.est_embedding_cost_usd ? `, about ${usd(r.est_embedding_cost_usd)}` : ""}.`);
      await refresh(key);
    } catch (err) {
      setSyncNote(err instanceof Error ? err.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  if (!authed) {
    return (
      <main className="admin">
        <form className="admin-card login" onSubmit={signIn}>
          <h1>Helpdesk admin</h1>
          <p className="muted">Enter the admin key from the server&apos;s .env. It is kept in this tab&apos;s memory only and is gone when you close or refresh it.</p>
          <label htmlFor="admin-key">Admin key</label>
          <input id="admin-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          <button type="submit" disabled={!key.trim()}>Open</button>
          {error && <div className="admin-error" role="alert">{error}</div>}
          <a href="#/" className="muted">Back to the chat</a>
        </form>
      </main>
    );
  }

  const cur = monitoring?.current;
  const base = experiments?.baseline;
  const rag = (m: Record<string, ModeMetrics> | undefined) => m?.rag;
  return (
    <main className="admin">
      <header className="admin-head">
        <h1>Helpdesk admin</h1>
        <span className={`status status-${monitoring?.status ?? "ok"}`}>{monitoring?.status ?? "ok"}</span>
        <button type="button" className="ghost" onClick={() => void refresh(key)}>Refresh</button>
        <a href="#/" className="muted">Chat</a>
      </header>
      {error && <div className="admin-error" role="alert">{error}</div>}

      <section className="admin-card" aria-labelledby="mon">
        <h2 id="mon">Last {monitoring?.window_hours} hours</h2>
        {cur && (
          <div className="tiles">
            <Tile label="Requests" value={String(cur.requests)} note={`${monitoring?.reference.requests} in the week before`} />
            <Tile label="Errors" value={pct(cur.error_rate)} note={`${cur.errors} failed`} tone={(cur.error_rate ?? 0) > 0.05 ? "bad" : undefined} />
            <Tile label="Latency p50 / p95" value={`${ms(cur.latency_ms.p50)}`} note={`p95 ${ms(cur.latency_ms.p95)}`} />
            <Tile label="First word p50" value={ms(cur.first_word_ms.p50)} note={`p95 ${ms(cur.first_word_ms.p95)}`} />
            <Tile label="Cost / request" value={usd(cur.cost_usd_per_request)} note={`${usd(cur.cost_usd_total)} total`} />
            <Tile label="No passage found" value={pct(cur.no_evidence_rate)} note={`${cur.document_questions} document questions`} />
            <Tile label="Nearest passage" value={cur.best_distance.mean?.toFixed(3) ?? "–"} note="mean cosine distance (lower = closer)" />
            <Tile label="Thumbs down" value={pct(cur.feedback.thumbs_down_rate)} note={`${cur.feedback.votes} ratings`} />
          </div>
        )}
        <ul className="alerts">
          {monitoring?.alerts.length === 0 && <li className="alert alert-ok">No alerts.</li>}
          {monitoring?.alerts.map((a) => (
            <li key={a.code} className={`alert alert-${a.level}`}><strong>{a.level}</strong> {a.message}</li>
          ))}
        </ul>
      </section>

      <section className="admin-card" aria-labelledby="docs">
        <h2 id="docs">Documents</h2>
        {ingestion && (
          <>
            <p>
              Source: Google Drive {ingestion.drive_ready ? "(connected)" : "(not connected)"}. Automatic ingestion {ingestion.poll_enabled ? `on, every ${ingestion.poll_interval_seconds} s` : "off"}.
              Last successful sync: <strong>{age(ingestion.seconds_since_last_success)}</strong>.
              {ingestion.drive_error && <span className="admin-error"> {ingestion.drive_error}</span>}
            </p>
            <div className="row-actions">
              <button type="button" onClick={() => void sync()} disabled={syncing || !ingestion.drive_ready}>{syncing ? "Syncing…" : "Sync Drive now"}</button>
              {syncNote && <span role="status">{syncNote}</span>}
            </div>
            <table>
              <thead><tr><th>File</th><th>Status</th><th>Chunks</th><th>Indexed</th></tr></thead>
              <tbody>
                {ingestion.files.filter((f) => f.status !== "deleted").map((f) => (
                  <tr key={`${f.source}:${f.name}`}>
                    <td>{f.name}<div className="muted">{f.source}</div></td>
                    <td><span className={`pill pill-${f.status}`}>{f.status}</span>{f.last_error && <div className="muted">{f.last_error}</div>}</td>
                    <td>{f.chunk_count}</td><td>{f.indexed_at ? new Date(f.indexed_at).toLocaleString() : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="admin-card" aria-labelledby="eval">
        <h2 id="eval">Evaluation (Model 2, document-grounded)</h2>
        <p className="muted">The accepted baseline and the latest runs on the golden question set. A change may replace the baseline only if no critical gate regresses (docs/PROMOTION_POLICY.md).</p>
        <table>
          <thead><tr><th>Run</th><th>Accuracy</th><th>Evidence reached model</th><th>Citation hit</th><th>Correct refusals</th><th>p95</th><th>Cost</th></tr></thead>
          <tbody>
            {base && <EvalRow id={base.run_id} note={`BASELINE: ${base.reason.slice(0, 80)}`} m={rag(base.modes)} />}
            {experiments?.runs.map((r) => (
              <EvalRow key={r.run_id} id={r.run_id} note={`${r.git?.commit?.slice(0, 7) ?? "?"}${r.git?.dirty ? " + uncommitted" : ""}`} m={rag(r.modes)} />
            ))}
            {!base && experiments?.runs.length === 0 && <tr><td colSpan={7} className="muted">No evaluation runs yet. Run scripts/run_evaluation.py.</td></tr>}
          </tbody>
        </table>
      </section>
    </main>
  );
}
