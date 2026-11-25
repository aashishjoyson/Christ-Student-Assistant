import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  FlowAuthError, getEvidently, getJson, getRecent, getServices, openEvidentlyReport, streamFlow,
  type EvidentlySummary, type FlowEvent, type ServiceInfo,
} from "../api/flow";
import type { Experiments, MonitoringReport } from "../api/admin";
import { groupTraces, num, serviceStates, stepsOf, text, type NodeState, type Trace } from "../lib/flowModel";
import {
  EMAIL_STEPS, EXPLAIN, LIVE_EDGES, LIVE_NODES, MODE_LABELS_FLOW, NODE_H, NODE_W, OUTCOME_COLORS, OUTCOME_LABELS, PIPE_EDGES, PIPE_NODES,
  type MapNode,
} from "./flowData";

type Tab = "live" | "pipeline" | "email" | "evidently";
type Services = Record<string, ServiceInfo>;

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 1000) / 10}%`);
const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ms`);
const time = (iso: string) => new Date(iso).toLocaleTimeString();

// ---------------------------------------------------------------------------------------------------- the map
function FlowMap({ nodes, edges, states, services, notes, picked, onPick }: {
  nodes: MapNode[]; edges: [string, string][]; states: Record<string, NodeState>; services: Services; notes: Record<string, string>;
  picked: string | null; onPick: (id: string) => void;
}) {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const busy = (id: string) => states[id] !== undefined && states[id] !== "idle";
  return (
    <svg className="flow-map" viewBox="0 0 940 430" role="img" aria-label="Architecture map: boxes light up as a request passes through them">
      {edges.map(([a, b]) => (
        <line key={`${a}-${b}`} className={`edge${busy(a) && busy(b) ? " on" : ""}`}
          x1={byId[a].x + NODE_W / 2} y1={byId[a].y + NODE_H / 2} x2={byId[b].x + NODE_W / 2} y2={byId[b].y + NODE_H / 2} />
      ))}
      {nodes.map((n) => (
        <g key={n.id} transform={`translate(${n.x},${n.y})`} className={`node ${states[n.id] ?? "idle"}${picked === n.id ? " picked" : ""}`}
          onClick={() => onPick(n.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onPick(n.id)}>
          <rect width={NODE_W} height={NODE_H} rx={12} />
          <text x={NODE_W / 2} y={notes[n.id] ? 23 : 33} textAnchor="middle" className="nl">{services[n.id]?.label ?? n.id}</text>
          {notes[n.id] && <text x={NODE_W / 2} y={43} textAnchor="middle" className="nn">{notes[n.id]}</text>}
        </g>
      ))}
    </svg>
  );
}

function Detail({ event, service, services }: { event: FlowEvent | null; service: string | null; services: Services }) {
  if (event) {
    const info = EXPLAIN[event.name];
    return (
      <div className="flow-detail">
        <h3>{info?.title ?? event.name}</h3>
        <p>{info?.text ?? event.label}</p>
        <p className="muted small">{services[event.service]?.label ?? event.service} · {event.ms !== null ? ms(event.ms) : "no duration"} · {time(event.ts)}</p>
        <dl>
          {Object.entries(event.detail).filter(([, v]) => v !== null && v !== "").map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>
          ))}
        </dl>
      </div>
    );
  }
  if (service && services[service]) {
    return <div className="flow-detail"><h3>{services[service].label}</h3><p>{services[service].role}</p></div>;
  }
  return <div className="flow-detail"><p className="muted">Tap a box on the map or a step in the timeline to see what it does.</p></div>;
}

// ---------------------------------------------------------------------------------------------------- live request
function LiveTab({ traces, services, selected, onSelect }: { traces: Trace[]; services: Services; selected: string | null; onSelect: (id: string | null) => void }) {
  const chats = traces.filter((t) => t.kind === "chat");
  const trace = chats.find((t) => t.id === selected) ?? chats[0];
  const [pickedEvent, setPickedEvent] = useState<FlowEvent | null>(null);
  const [pickedService, setPickedService] = useState<string | null>(null);
  const states = useMemo(() => serviceStates(trace), [trace]);
  const rows = trace ? stepsOf(trace) : [];
  const longest = Math.max(1, ...rows.map((r) => r.e.ms ?? 0));
  const end = trace?.events.find((e) => e.kind === "request" && e.phase !== "start");
  const d = end?.detail ?? {};
  const path = Array.isArray(d.path) ? (d.path as string[]).join(" → ") : "";
  return (
    <div>
      {!trace && <p className="flow-empty">Waiting for a message. Ask something in the chat on the left and watch the map.</p>}
      {chats.length > 1 && (
        <div className="flow-picker">
          {chats.slice(0, 8).map((t, i) => (
            <button key={t.id} type="button" className={`flow-pick${t.id === trace?.id ? " on" : ""}${t.failed ? " bad" : ""}`} onClick={() => onSelect(i === 0 ? null : t.id)}>
              {i === 0 ? "latest" : time(t.startedAt)}
            </button>
          ))}
        </div>
      )}
      <FlowMap nodes={LIVE_NODES} edges={LIVE_EDGES} states={states} services={services} notes={{}} picked={pickedService}
        onPick={(id) => { setPickedService(id); setPickedEvent(null); }} />
      {trace && end && (
        <div className="flow-tiles">
          <div><span>Total</span><strong>{ms(trace.totalMs)}</strong></div>
          <div><span>First word</span><strong>{ms(num(d.first_token_ms))}</strong></div>
          <div><span>Tokens in / out</span><strong>{num(d.input_tokens) ?? "–"} / {num(d.output_tokens) ?? "–"}</strong></div>
          <div><span>Est. cost</span><strong>{num(d.est_cost_usd) === null ? "–" : `$${(num(d.est_cost_usd) ?? 0).toFixed(5)}`}</strong></div>
          <div><span>Answered by</span><strong>{text(d.handled_by) || "–"}</strong></div>
          <div><span>Model called</span><strong>{d.llm_called ? "yes" : "no"}</strong></div>
        </div>
      )}
      {path && <p className="muted small">Path: {path}</p>}
      <div className="flow-split">
        <ol className="flow-steps">
          {rows.map(({ e, running }) => (
            <li key={`${e.seq}-${e.phase}`} className={`step ${running ? "running" : e.phase}${pickedEvent?.seq === e.seq ? " picked" : ""}`}
              onClick={() => { setPickedEvent(e); setPickedService(null); }}>
              <span className="svc">{services[e.service]?.label ?? e.service}</span>
              <span className="lbl">{running ? `${e.label}…` : e.label}</span>
              <span className="bar"><i style={{ width: `${Math.max(2, ((e.ms ?? 0) / longest) * 100)}%` }} /></span>
              <span className="ms">{running ? "running" : ms(e.ms)}</span>
            </li>
          ))}
        </ol>
        <Detail event={pickedEvent} service={pickedService} services={services} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- LLMOps pipeline
interface DriveStatus { files: { name: string; status: string; chunk_count: number }[]; counts: Record<string, number>; poll_interval_seconds: number; seconds_since_last_success: number | null; retriever?: { chunks?: number } }

function PipelineTab({ adminKey, traces, services }: { adminKey: string; traces: Trace[]; services: Services }) {
  const [drive, setDrive] = useState<DriveStatus | null>(null);
  const [exp, setExp] = useState<Experiments | null>(null);
  const [mon, setMon] = useState<MonitoringReport | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      getJson<DriveStatus>("/api/admin/drive/status", adminKey).then((v) => alive && setDrive(v)).catch(() => undefined);
      getJson<Experiments>("/api/admin/experiments/summary", adminKey).then((v) => alive && setExp(v)).catch(() => undefined);
      getJson<MonitoringReport>("/api/admin/monitoring/summary?hours=24&reference_hours=168", adminKey).then((v) => alive && setMon(v)).catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 15000);
    return () => { alive = false; window.clearInterval(id); };
  }, [adminKey]);

  const sync = traces.find((t) => t.kind === "sync");
  const states = useMemo(() => serviceStates(sync), [sync]);
  const latest = exp?.runs[0];
  const base = exp?.baseline;
  const notes: Record<string, string> = {
    drive: drive ? `${drive.files.length} files` : "", poller: drive ? `every ${drive.poll_interval_seconds}s` : "",
    ingest: drive ? `${drive.counts.indexed ?? 0} indexed` : "", chroma: drive?.retriever?.chunks ? `${drive.retriever.chunks} chunks` : "",
    eval: latest?.modes.rag ? `rag ${pct(latest.modes.rag.answer_accuracy)}` : "", gate: base ? `baseline ${pct(base.modes.rag?.answer_accuracy)}` : "",
    evidently: latest ? latest.run_id.slice(5, 13) : "", ci: "every push", traces: mon ? `${mon.current.requests} in 24h` : "",
    monitor: mon ? mon.status : "", training: "T4 · 44 steps", llm_modal: "scale to zero",
  };
  const syncEvents = sync ? sync.events.filter((e) => e.phase !== "start") : [];
  return (
    <div>
      <FlowMap nodes={PIPE_NODES} edges={PIPE_EDGES} states={states} services={services} notes={notes} picked={picked} onPick={setPicked} />
      <div className="flow-detail">
        {picked && services[picked] ? <><h3>{services[picked].label}</h3><p>{services[picked].role}</p></> : <p className="muted">Tap a box for what it does. During a Drive sync the data row lights up live.</p>}
      </div>
      <div className="flow-cards">
        <div className="flow-card"><h3>Data pipeline</h3>
          <p>{drive ? `${drive.files.length} documents, ${drive.retriever?.chunks ?? "?"} chunks. Last good sync ${drive.seconds_since_last_success === null ? "never" : `${Math.round(drive.seconds_since_last_success / 60)} min ago`}.` : "Loading…"}</p>
          <p className="muted small">Edits, new files and deletions reach the index on their own; unchanged files are skipped by checksum.</p></div>
        <div className="flow-card"><h3>Evaluation loop</h3>
          <p>{latest ? `Latest run ${latest.run_id}: Model 2 ${pct(latest.modes.rag?.answer_accuracy)}${latest.modes.rag_peft ? `, Model 3 ${pct(latest.modes.rag_peft.answer_accuracy)}` : ""}.` : "No run yet."} {base ? `Accepted baseline ${pct(base.modes.rag?.answer_accuracy)}.` : ""}</p>
          <p className="muted small">The gate compares a run with the baseline; a critical regression blocks promotion.</p></div>
        <div className="flow-card"><h3>Monitoring</h3>
          <p>{mon ? `Status ${mon.status}. ${mon.current.requests} requests in 24 h, p95 ${ms(mon.current.latency_ms.p95)}, ${mon.alerts.length} alert(s).` : "Loading…"}</p>
          <p className="muted small">Built from text-free trace lines plus thumbs feedback; alerts need a minimum sample size.</p></div>
      </div>
      {syncEvents.length > 0 && (
        <div className="flow-card"><h3>Latest Drive sync (live)</h3>
          <ol className="flow-steps">{syncEvents.map((e) => (
            <li key={e.seq} className={`step ${e.phase}`}><span className="svc">{services[e.service]?.label ?? e.service}</span><span className="lbl">{e.label}</span><span className="ms">{time(e.ts)}</span></li>
          ))}</ol></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- email
function EmailTab({ traces, services }: { traces: Trace[]; services: Services }) {
  const trace = traces.find((t) => t.kind === "chat" && t.events.some((e) => e.name === "check_resend_eligibility"));
  const done = (name: string) => trace?.events.find((e) => e.name === name && e.phase !== "start");
  const rules = done("check_resend_eligibility");
  const result = done("send_interview_email");
  const provider = text(result?.detail.provider);
  return (
    <div>
      <p className="flow-intro">The interview email is the one action this helpdesk takes. The model never touches it: rules and a database decide, and the recipient is read from the database inside the send function.</p>
      <ol className="flow-email">
        {EMAIL_STEPS.map((s, i) => {
          const e = done(s.name);
          const skipped = !e && trace && s.name.startsWith("smtp_") && provider === "console";
          return (
            <li key={s.name} className={e ? (e.phase === "error" ? "bad" : "ok") : skipped ? "skip" : ""}>
              <span className="n">{i + 1}</span>
              <div><strong>{s.title}</strong><p>{s.text}</p>
                <small>{e ? (e.ms !== null ? ms(e.ms) : "done") : skipped ? "not used (simulated)" : trace ? "not reached" : "waiting"}</small></div>
            </li>
          );
        })}
      </ol>
      {!trace && <p className="flow-empty">No email request yet. In the chat: verify as CUAPP-DEMO-0001, then say “I have not received my interview email”.</p>}
      {rules && (
        <div className="flow-card">
          <h3>Last request</h3>
          <p>Decision: <strong>{rules.detail.eligible ? "allowed" : `refused (${text(rules.detail.reason)})`}</strong>{rules.detail.masked_recipient ? ` · recipient ${text(rules.detail.masked_recipient)}` : ""}</p>
          {result && <p>Result: <strong>{text(result.detail.status)}</strong> via {provider || "?"}{result.detail.mail_id ? ` · message id ${text(result.detail.mail_id)}` : ""}{result.detail.error ? ` · ${text(result.detail.error)}` : ""}</p>}
          <p className="muted small">{services.email?.role}</p>
        </div>
      )}
      <div className="flow-card"><h3>What stops abuse</h3>
        <ul className="flow-list">
          <li>The recipient comes from the database, so “send it to someone@elsewhere.com” changes nothing.</li>
          <li>The allowlist is checked before anything is reserved or any connection is opened.</li>
          <li>One send per 15-minute window (reserve with a UNIQUE key, then send), at most 3 a day.</li>
          <li>TLS is mandatory with certificate checks; one plain address; no line breaks in headers.</li>
          <li>“Sent” is recorded only after the server accepts; a failure is audited and frees the window.</li>
        </ul></div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- Evidently
function EvidentlyTab({ adminKey }: { adminKey: string }) {
  const [data, setData] = useState<EvidentlySummary | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { getEvidently(adminKey).then(setData).catch((e: Error) => setNote(e.message)); }, [adminKey]);
  const modes = Object.entries(data?.by_mode ?? {});
  return (
    <div>
      <div className="flow-card">
        <h3>What Evidently is doing here</h3>
        <ul className="flow-list">
          <li><strong>It turns each evaluation run into a report and tests.</strong> The deterministic checker has already scored every answer against the golden set; Evidently summarises the outcomes per model and per category.</li>
          <li><strong>It enforces one critical test:</strong> no citation may point at a passage that was not supplied to the model.</li>
          <li><strong>It does not decide promotions.</strong> The gate (compare.py) compares runs with the accepted baseline; Evidently is the evidence for one run.</li>
          <li>It also builds the adversarial, fairness-parity and data-drift reports. It runs only in scripts, never inside the API.</li>
        </ul>
      </div>
      {note && <p className="flow-empty">{note}</p>}
      {data && !data.available && <p className="flow-empty">No Evidently report yet. Run <code>python scripts/run_evaluation.py --modes rag --evidently</code>.</p>}
      {data?.available && (
        <>
          <div className="flow-card">
            <h3>Latest run: {data.run_id}</h3>
            <p className="muted small">Report generated {data.generated_at}. {data.tests_passed} of {data.tests?.length ?? 0} tests passed.</p>
            {(data.tests ?? []).map((t) => (
              <p key={t.name} className={`flow-test ${String(t.status).toUpperCase() === "SUCCESS" ? "ok" : "bad"}`}>
                <strong>{String(t.status).toUpperCase() === "SUCCESS" ? "PASS" : String(t.status)}</strong> {t.name}
              </p>
            ))}
            {data.html_available && <button type="button" className="btn-primary" onClick={() => openEvidentlyReport(adminKey).catch((e: Error) => setNote(e.message))}>Open the full report ({data.html_kb} KB)</button>}
          </div>
          <div className="flow-card">
            <h3>Outcomes per model (answers in the golden set)</h3>
            {modes.map(([mode, counts]) => {
              const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
              return (
                <div key={mode} className="flow-stack-row">
                  <span>{MODE_LABELS_FLOW[mode] ?? mode}</span>
                  <div className="flow-stack">{(data.outcomes ?? []).map((o) => counts[o] ? <i key={o} title={`${OUTCOME_LABELS[o] ?? o}: ${counts[o]}`} style={{ width: `${(counts[o] / total) * 100}%`, background: OUTCOME_COLORS[o] ?? "#999" }}>{counts[o]}</i> : null)}</div>
                </div>
              );
            })}
            <p className="flow-legend">{(data.outcomes ?? []).map((o) => <span key={o}><i style={{ background: OUTCOME_COLORS[o] }} />{OUTCOME_LABELS[o] ?? o}</span>)}</p>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- the page
export function FlowPage() {
  const [key, setKey] = useState("");
  const [authed, setAuthed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [services, setServices] = useState<Services>({});
  const [events, setEvents] = useState<FlowEvent[]>([]);
  const [tab, setTab] = useState<Tab>("live");
  const [selected, setSelected] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const cursor = useRef(0);
  const traces = useMemo(() => groupTraces(events), [events]);

  async function connect(e: FormEvent) {
    e.preventDefault();
    try {
      const [svc, recent] = await Promise.all([getServices(key), getRecent(key, 0)]);
      setServices(svc);
      setEvents(recent.events);
      cursor.current = recent.last_seq;
      setAuthed(true);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect.");
    }
  }

  useEffect(() => {
    if (!authed) return;
    const controller = new AbortController();
    (async () => {
      while (!controller.signal.aborted) {
        try {
          const recent = await getRecent(key, cursor.current); // after an API restart the numbers start again: resync
          if (recent.last_seq < cursor.current) { setEvents(recent.events); cursor.current = recent.last_seq; }
          setLive(true);
          await streamFlow(key, cursor.current, (ev) => { cursor.current = ev.seq; setEvents((prev) => [...prev.slice(-1500), ev]); }, controller.signal);
        } catch (err) {
          if (controller.signal.aborted) return;
          if (err instanceof FlowAuthError) { setAuthed(false); setError(err.message); return; }
        }
        setLive(false);
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    })();
    return () => controller.abort();
  }, [authed, key]);

  if (!authed) {
    return (
      <div className="flow-login">
        <form className="admin-card login" onSubmit={connect}>
          <h1>Live flow</h1>
          <p className="muted">Shows, as it happens, which service handles each message. Enter the admin key (the same one as the admin page; kept in memory only).</p>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Admin key" autoFocus />
          <button type="submit" className="btn-primary">Connect</button>
          {error && <p className="admin-error" role="alert">{error}</p>}
        </form>
      </div>
    );
  }

  return (
    <div className="flow">
      <header className="flow-head">
        <h1>Live flow</h1>
        <span className={`flow-dot${live ? " on" : ""}`} />
        <span className="muted small">{live ? "streaming" : "reconnecting…"} · {events.length} events · text-free: no message text is ever shown here</span>
        <a href="#/admin" className="flow-link">Admin page</a>
      </header>
      <div className="flow-body">
        <iframe className="flow-chat" src="/#/" title="The helpdesk chat" />
        <main className="flow-main">
          <nav className="flow-tabs">
            {([["live", "Live request"], ["pipeline", "LLMOps pipeline"], ["email", "Email"], ["evidently", "Evidently"]] as [Tab, string][]).map(([id, label]) => (
              <button key={id} type="button" className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>
            ))}
          </nav>
          {tab === "live" && <LiveTab traces={traces} services={services} selected={selected} onSelect={setSelected} />}
          {tab === "pipeline" && <PipelineTab adminKey={key} traces={traces} services={services} />}
          {tab === "email" && <EmailTab traces={traces} services={services} />}
          {tab === "evidently" && <EvidentlyTab adminKey={key} />}
        </main>
      </div>
    </div>
  );
}
