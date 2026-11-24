import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, getHealth, streamChat } from "./api/client";
import type { Health, ModelMode, VerifyResponse } from "./api/types";
import { ApplicantPanel } from "./components/ApplicantPanel";
import { Backdrop } from "./components/Backdrop";
import { CloseIcon, LockIcon, PlusIcon, SendIcon, ShieldCheckIcon } from "./components/icons";
import { MessageView, type UiMessage } from "./components/MessageView";
import { ModelSelector } from "./components/ModelSelector";

// sessionStorage: cleared when the tab closes. Prototype trade-off (XSS-readable); see docs/ARCHITECTURE.md.
const CONV_KEY = "helpdesk.conversation_id";
const SESSION_KEY = "helpdesk.applicant_session";
const MESSAGES_KEY = "helpdesk.messages";
const MAX_SAVED_MESSAGES = 40;

// Generic example questions only: they fill the input box, they never send by themselves and carry no university facts.
const SUGGESTIONS = [
  "What are the attendance requirements?",
  "When is my interview?",
  "I have not received my interview email",
];

function loadSession(): VerifyResponse | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    const s = raw ? (JSON.parse(raw) as VerifyResponse) : null;
    return s && new Date(s.expires_at) > new Date() ? s : null;
  } catch {
    return null;
  }
}

/** The visible conversation survives a page refresh together with its conversation id (the server keeps the context). */
function loadMessages(): UiMessage[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(MESSAGES_KEY) ?? "[]") as UiMessage[];
    return Array.isArray(parsed) ? parsed.filter((m) => !("streaming" in m)) : [];
  } catch {
    return [];
  }
}

function errorText(code: string, message: string): string {
  return code === "model3_not_configured"
    ? "Model 3 is not configured yet, so it cannot answer. (No other model is substituted.)"
    : message;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [mode, setMode] = useState<ModelMode>("rag");
  const [messages, setMessages] = useState<UiMessage[]>(loadMessages);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [open, setOpen] = useState(true);
  const [showVerify, setShowVerify] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(() => sessionStorage.getItem(CONV_KEY));
  const [session, setSession] = useState<VerifyResponse | null>(loadSession);
  const listRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true); // follow the newest text unless the reader scrolled up
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    getHealth()
      .then((h) => { setHealth(h); setOffline(false); })
      .catch(() => { setHealth(null); setOffline(true); });
    return () => abortRef.current?.abort();
  }, []);

  // Scroll ONLY the message list. (scrollIntoView also scrolls every ancestor, including the page behind the widget:
  // that was the "everything slides up and goes white" glitch.)
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    try {
      const saved = messages.filter((m) => !("streaming" in m)).slice(-MAX_SAVED_MESSAGES);
      sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(saved));
    } catch {
      /* storage unavailable: the chat still works, it just will not survive a refresh */
    }
  }, [messages]);

  function onScroll() {
    const el = listRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    stickRef.current = true;
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", text },
      { id: assistantId, role: "assistant", streaming: { text: "" } },
    ]);
    setSending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    // The bubble keeps the same React key from "typing" to the final answer, so nothing re-mounts or flashes.
    const replace = (m: UiMessage) => setMessages((prev) => prev.map((x) => (x.id === assistantId ? m : x)));
    const grow = (fn: (s: { text: string }) => object) =>
      setMessages((prev) => prev.map((x) => (x.id === assistantId && "streaming" in x ? { ...x, streaming: { ...x.streaming, ...fn(x.streaming) } } : x)));
    let finished = false;
    try {
      await streamChat(
        { message: text, modelMode: mode, conversationId, applicantToken: session?.session_token ?? null },
        (ev) => {
          if (ev.type === "start") {
            grow(() => ({ handledBy: ev.handled_by, notice: ev.notice ?? null }));
          } else if (ev.type === "delta") {
            grow((s) => ({ text: s.text + ev.text }));
          } else if (ev.type === "final") {
            finished = true;
            setConversationId(ev.response.conversation_id);
            sessionStorage.setItem(CONV_KEY, ev.response.conversation_id);
            replace({ id: assistantId, role: "assistant", response: ev.response });
          } else if (ev.type === "error") {
            finished = true;
            replace({ id: assistantId, role: "error", text: errorText(ev.code, ev.message) });
          }
        },
        controller.signal,
      );
      if (!finished) replace({ id: assistantId, role: "error", text: "The connection ended before the answer was complete. Please try again." });
    } catch (err) {
      if (controller.signal.aborted) return; // New chat was pressed: the placeholder is already gone
      replace({
        id: assistantId,
        role: "error",
        text: err instanceof ApiError ? errorText(err.code, err.message) : "Could not reach the backend. Is it running on port 8000?",
      });
    } finally {
      if (abortRef.current === controller) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }

  function newChat() {
    abortRef.current?.abort();
    abortRef.current = null;
    setSending(false);
    setMessages([]);
    setConversationId(null);
    setInput("");
    stickRef.current = true;
    try {
      sessionStorage.removeItem(CONV_KEY);
      sessionStorage.removeItem(MESSAGES_KEY);
    } catch {
      /* ignore */
    }
  }

  function onVerified(s: VerifyResponse) {
    setSession(s);
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
    setShowVerify(false);
  }

  function signOut() {
    setSession(null);
    sessionStorage.removeItem(SESSION_KEY);
    setShowVerify(false);
  }

  const status = offline ? "Backend offline" : health ? "Student Helpdesk · AI assistant" : "Connecting...";

  return (
    <>
      <Backdrop />

      {!open && (
        <button type="button" className="launcher" onClick={() => setOpen(true)} aria-label="Open the student helpdesk chat">
          <img className="crest" src="/christ-logo.png" alt="" />
          <span>Ask the Helpdesk</span>
        </button>
      )}

      {open && (
        <section className="widget" aria-label="Student helpdesk chat">
          <header className="widget-head">
            <img className="crest" src="/christ-logo.png" alt="Christ University emblem" />
            <div className="head-text">
              <h1>Christ University</h1>
              <p><span className={`live${health ? "" : " off"}`} aria-hidden="true" />{status}</p>
            </div>
            <button type="button" className="icon-btn" onClick={newChat} aria-label="Start a new chat" title="New chat (clears the conversation)">
              <PlusIcon />
            </button>
            <button
              type="button"
              className={`chip-btn${session ? " ok" : ""}`}
              onClick={() => setShowVerify((v) => !v)}
              aria-expanded={showVerify}
              aria-label={session ? `Verified as ${session.applicant.first_name}. Open applicant details` : "Verify as an applicant"}
            >
              {session ? <ShieldCheckIcon /> : <LockIcon />}
              <span>{session ? session.applicant.first_name : "Verify"}</span>
            </button>
            <button type="button" className="icon-btn" onClick={() => setOpen(false)} aria-label="Minimise chat">
              <CloseIcon />
            </button>
          </header>

          <ModelSelector value={mode} onChange={setMode} health={health} />

          <div className="messages" ref={listRef} onScroll={onScroll} role="log" aria-live="polite" aria-label="Conversation">
            {messages.length === 0 && (
              <div className="empty">
                <img className="crest big" src="/christ-logo.png" alt="" />
                <h2>Hi, how can I help?</h2>
                <p className="muted">Ask an academic question, or verify to ask about your application.</p>
                <div className="chips">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className="chip" onClick={() => setInput(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => <MessageView key={m.id} message={m} />)}
          </div>

          {showVerify && (
            <div className="sheet" role="dialog" aria-label="Applicant verification" onKeyDown={(e) => e.key === "Escape" && setShowVerify(false)}>
              <button type="button" className="icon-btn sheet-close" onClick={() => setShowVerify(false)} aria-label="Close verification">
                <CloseIcon />
              </button>
              <ApplicantPanel session={session} onVerified={onVerified} onSignOut={signOut} />
            </div>
          )}

          <form className="composer" onSubmit={send}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your question..." maxLength={2000} aria-label="Your question" />
            <button type="submit" className="send" disabled={sending || !input.trim()} aria-label="Send"><SendIcon /></button>
          </form>
          <p className="disclaimer">Academic prototype &middot; AI can make mistakes &middot; not an official university service</p>
        </section>
      )}
    </>
  );
}
