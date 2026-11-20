import type { ChatResponse } from "../api/types";

export type UiMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse }
  | { id: string; role: "error"; text: string };

const ACTION_TEXT: Record<string, string> = {
  sent: "Email sent",
  simulated: "Email simulated (demo mode)",
  failed: "Email failed",
  not_eligible: "Not eligible to resend",
  verification_required: "Verification required",
};

function citationLocation(c: ChatResponse["citations"][number]) {
  return [c.page !== null ? `page ${c.page}` : null, c.section].filter(Boolean).join(", ");
}

export function MessageView({ message }: { message: UiMessage }) {
  if (message.role === "user") return <div className="bubble user">{message.text}</div>;
  if (message.role === "error") return <div className="bubble error">{message.text}</div>;

  const r = message.response;
  return (
    <div className="bubble assistant">
      {r.notice && <div className="notice">{r.notice}</div>}
      <div className="answer">{r.answer}</div>

      {r.citations.length > 0 && (
        <div className="citations">
          <strong>{r.citations.some((c) => c.cited) ? "Sources" : "Retrieved (not explicitly cited)"}</strong>
          <ul>
            {r.citations.map((c) => (
              <li key={c.chunk_id}>
                [{c.index}] {c.source_url ? <a href={c.source_url} target="_blank" rel="noreferrer">{c.source_name}</a> : c.source_name}
                {citationLocation(c) && <span className="muted"> ({citationLocation(c)})</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.action && (
        <div className={`action action-${r.action.status}`}>
          {ACTION_TEXT[r.action.status] ?? r.action.status}
          {r.action.masked_recipient && <> &middot; {r.action.masked_recipient}</>}
        </div>
      )}

      <div className="meta">
        <span className="badge">{r.handled_by.label}</span>
        {r.handled_by.model && <span className="muted">{r.handled_by.model}</span>}
        {r.handled_by.adapter_id && <span className="muted">adapter: {r.handled_by.adapter_id}</span>}
        <span className="muted">{r.usage.latency_ms} ms</span>
      </div>
      <details className="workflow">
        <summary>How this was handled</summary>
        <code>{r.workflow_path.join(" → ")}</code>
      </details>
    </div>
  );
}
