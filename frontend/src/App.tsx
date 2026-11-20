import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, getHealth, sendChat } from "./api/client";
import type { Health, ModelMode, VerifyResponse } from "./api/types";
import { ApplicantPanel } from "./components/ApplicantPanel";
import { MessageView, type UiMessage } from "./components/MessageView";
import { ModelSelector } from "./components/ModelSelector";

// sessionStorage: cleared when the tab closes. Prototype trade-off (XSS-readable); see docs/ARCHITECTURE.md.
const CONV_KEY = "helpdesk.conversation_id";
const SESSION_KEY = "helpdesk.applicant_session";

function loadSession(): VerifyResponse | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    const s = raw ? (JSON.parse(raw) as VerifyResponse) : null;
    return s && new Date(s.expires_at) > new Date() ? s : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [mode, setMode] = useState<ModelMode>("rag");
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(() => sessionStorage.getItem(CONV_KEY));
  const [session, setSession] = useState<VerifyResponse | null>(loadSession);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const add = (m: UiMessage) => setMessages((prev) => [...prev, m]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    add({ id: crypto.randomUUID(), role: "user", text });
    setSending(true);
    try {
      const res = await sendChat({ message: text, modelMode: mode, conversationId, applicantToken: session?.session_token ?? null });
      setConversationId(res.conversation_id);
      sessionStorage.setItem(CONV_KEY, res.conversation_id);
      add({ id: res.message_id, role: "assistant", response: res });
    } catch (err) {
      const msg =
        err instanceof ApiError && err.code === "model3_not_configured"
          ? "Model 3 is not configured yet, so it cannot answer. (No other model is substituted.)"
          : err instanceof ApiError
            ? err.message
            : "Could not reach the backend. Is it running on port 8000?";
      add({ id: crypto.randomUUID(), role: "error", text: msg });
    } finally {
      setSending(false);
    }
  }

  function onVerified(s: VerifyResponse) {
    setSession(s);
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
  }

  function signOut() {
    setSession(null);
    sessionStorage.removeItem(SESSION_KEY);
  }

  return (
    <div className="layout">
      <header>
        <h1>Student Helpdesk <span className="muted small">academic prototype</span></h1>
        <ModelSelector value={mode} onChange={setMode} health={health} />
      </header>
      <main className="chat">
        <div className="messages">
          {messages.length === 0 && (
            <p className="muted empty">Ask an academic question, or verify on the right to ask about your application.</p>
          )}
          {messages.map((m) => <MessageView key={m.id} message={m} />)}
          {sending && <div className="bubble assistant muted">Thinking...</div>}
          <div ref={bottomRef} />
        </div>
        <form className="composer" onSubmit={send}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your question..." maxLength={2000} />
          <button type="submit" disabled={sending || !input.trim()}>Send</button>
        </form>
      </main>
      <ApplicantPanel session={session} onVerified={onVerified} onSignOut={signOut} />
    </div>
  );
}
