// What the dashboard draws and says. Boxes are keyed by the same ids the backend publishes (backend/app/core/flow.py SERVICES).

export interface MapNode { id: string; x: number; y: number }

export const NODE_W = 150;
export const NODE_H = 56;

/** The request path: left to right, models on the right. */
export const LIVE_NODES: MapNode[] = [
  { id: "browser", x: 10, y: 190 }, { id: "api", x: 190, y: 190 }, { id: "graph", x: 380, y: 190 }, { id: "rules", x: 380, y: 50 },
  { id: "traces", x: 190, y: 350 }, { id: "sqlite", x: 380, y: 350 }, { id: "email", x: 570, y: 350 },
  { id: "embedder", x: 570, y: 20 }, { id: "chroma", x: 570, y: 100 }, { id: "rerank", x: 570, y: 180 },
  { id: "llm_openai", x: 770, y: 100 }, { id: "llm_modal", x: 770, y: 190 },
];
export const LIVE_EDGES: [string, string][] = [
  ["browser", "api"], ["api", "graph"], ["graph", "rules"], ["api", "traces"], ["graph", "sqlite"], ["graph", "email"],
  ["graph", "embedder"], ["embedder", "chroma"], ["chroma", "rerank"], ["graph", "llm_openai"], ["graph", "llm_modal"],
];

/** The LLMOps loop: data pipeline on top, measuring in the middle, observing and fine-tuning below. */
export const PIPE_NODES: MapNode[] = [
  { id: "drive", x: 10, y: 30 }, { id: "poller", x: 200, y: 30 }, { id: "ingest", x: 390, y: 30 }, { id: "embedder", x: 580, y: 30 }, { id: "chroma", x: 770, y: 30 },
  { id: "eval", x: 10, y: 190 }, { id: "evidently", x: 200, y: 190 }, { id: "gate", x: 390, y: 190 }, { id: "ci", x: 580, y: 190 },
  { id: "traces", x: 580, y: 350 }, { id: "monitor", x: 390, y: 350 },
  { id: "training", x: 10, y: 350 }, { id: "llm_modal", x: 200, y: 350 },
];
export const PIPE_EDGES: [string, string][] = [
  ["drive", "poller"], ["poller", "ingest"], ["ingest", "embedder"], ["embedder", "chroma"],
  ["eval", "evidently"], ["evidently", "gate"], ["gate", "ci"],
  ["traces", "monitor"], ["monitor", "eval"], ["training", "llm_modal"],
];

export const EXPLAIN: Record<string, { title: string; text: string }> = {
  request: { title: "A message arrives", text: "The browser posts the message to FastAPI. The API applies a per-client rate limit, runs one LangGraph turn and streams the answer back as Server-Sent Events. Only the length of the message is shown here, never the text." },
  classify_intent: { title: "Intent rules", text: "Deterministic rules decide what the message is about: an academic question, an applicant lookup, a request to resend the email, help, or something to decline. They are free and instant. Only when they fall through to the default AND the message looks personal is one small model call made, and it may only return a single label." },
  intent_llm: { title: "A model call, only for a label", text: "The rules were unsure, so the hosted model was asked for ONE label from a fixed list. It cannot answer, cannot see applicant data and cannot write SQL: a wrong label only routes the message to a different template." },
  check_model_available: { title: "Is the chosen model configured?", text: "Model 3 never falls back. If its endpoint is not configured the turn ends with an error rather than silently using another model and mislabelling its answer." },
  retrieve_context: { title: "Search the university documents", text: "Models 2 and 3 share this step, so they see identical evidence. The question is embedded, Chroma returns 150 candidates by meaning, a lexical re-ranker rewards the question's rare words, and the best 8 under a distance cut-off are kept. If nothing passes, the answer is a fixed 'I could not find this' and no model is called." },
  embed_query: { title: "Embed the question", text: "OpenAI text-embedding-3-small turns the question into a vector so it can be compared with the stored chunks by meaning." },
  vector_search: { title: "Search Chroma", text: "Chroma returns the 150 nearest chunks. Each one carries its source file, page and version, which become the citations." },
  rerank: { title: "Re-rank by rare words", text: "A cheap lexical re-ranker (no model) moves up passages that contain the question's rare words, then keeps the best 8. It fixed near-misses that the vector search alone got wrong." },
  condense_query: { title: "Rewrite a follow-up", text: "A follow-up such as 'and for the end semester ones?' is restated as a standalone question, for searching only. The model still sees the real conversation." },
  direct_answer: { title: "Model 1: no documents", text: "The hosted model answers on its own. It opens with a notice that it has not checked official documents. This is the control that shows what retrieval is worth." },
  rag_answer: { title: "Model 2: answer from the passages", text: "The same hosted model, now given the numbered passages. It must cite [n] and say it could not find the answer when the passages do not contain it." },
  rag_peft_answer: { title: "Model 3: the fine-tuned model", text: "The same passages and prompt, answered by Qwen3-4B with our LoRA adapter on a Modal GPU. If the endpoint is cold the turn fails with an endpoint error; it never falls back to another model." },
  verify_identity: { title: "Verify the applicant", text: "A signed, expiring session token proves who is asking. Without one the visitor is asked to verify first and nothing private is read." },
  fetch_application_status: { title: "Read the applicant's own record", text: "A fixed repository query, scoped to the verified applicant. The model never writes SQL and never sees the result." },
  fetch_interview_details: { title: "Read the applicant's own interview", text: "A fixed query scoped to the verified applicant. The answer is written from a template." },
  check_resend_eligibility: { title: "Rules, then reserve", text: "The interview must be active and in the future, the 15-minute cooldown and the daily limit must allow it, and the recipient must be on the allowlist. Then the send is RESERVED with a UNIQUE key, so two concurrent requests cannot both send." },
  smtp_connect: { title: "Connect to the mail server", text: "A TCP connection to the SMTP server (smtp.gmail.com on port 587 in the demo)." },
  smtp_starttls: { title: "Encrypt the connection", text: "The connection is upgraded to TLS and the certificate and host name are verified. If the server does not offer it, nothing is sent: there is no plain-text fallback." },
  smtp_login: { title: "Log in", text: "The app password from .env authenticates the sender. It is never logged and is removed from any error text." },
  smtp_send: { title: "Hand the message to the server", text: "The recipient is read from the database inside the send function and is the only address on the envelope. The server accepting it is what 'sent' means; it does not prove delivery." },
  send_interview_email: { title: "The send, and its result", text: "The fixed template is filled from the database and sent. The result is sent, simulated (written to the outbox only) or failed. A failure is recorded and frees the cooldown window so the student can retry." },
  record_notification: { title: "Audit", text: "The outcome is written to the notification table with the provider, the server's message id and any short error." },
  compose_applicant_response: { title: "Write the answer", text: "A fixed template turns the database result into a sentence. No model is involved, so nothing can be invented." },
  general_help: { title: "Help text", text: "A fixed reply listing what the helpdesk can do." },
  safe_fallback: { title: "Declined", text: "The helpdesk answers and looks up; it never changes grades, fees, applications or interview slots, so those requests get a fixed refusal." },
  trace: { title: "One text-free trace line", text: "Model, tokens, cost, retrieval distance and the path taken are appended to the trace log. The message text is not stored. Monitoring and drift reports are built from these lines." },
  sync: { title: "A Drive sync", text: "The poller (or the admin button) lists the Drive folder, skips files whose checksum is unchanged, and re-indexes the rest. One sync runs at a time." },
  list: { title: "List the source", text: "The folder listing: names, versions and checksums only. Nothing is downloaded yet." },
  file: { title: "One file", text: "Unchanged files are skipped without being downloaded. Changed files are parsed, chunked, embedded and swapped in; the old version is removed only after the new one is in. One bad file never stops the sync." },
};

export const EMAIL_STEPS: { name: string; title: string; text: string }[] = [
  { name: "verify_identity", title: "Verify", text: "A signed session proves who is asking." },
  { name: "check_resend_eligibility", title: "Rules + reserve", text: "Interview active, cooldown and daily limit, allowlist, then a UNIQUE reservation." },
  { name: "smtp_connect", title: "Connect", text: "Open the connection to the mail server." },
  { name: "smtp_starttls", title: "Encrypt", text: "TLS with certificate checks; no plain-text fallback." },
  { name: "smtp_login", title: "Log in", text: "App password from .env; never logged." },
  { name: "smtp_send", title: "Hand over", text: "Only the registered address is on the envelope." },
  { name: "send_interview_email", title: "Result", text: "Sent means the server accepted it, not delivered." },
  { name: "record_notification", title: "Audit", text: "Outcome written to the notification table." },
];

export const OUTCOME_COLORS: Record<string, string> = {
  correct: "#1f8a4c", correct_refusal: "#7fc79a", false_refusal: "#e3b43a", wrong_answer: "#c4452d", unsupported_answer: "#7b1f1f", error: "#6b7280",
};
export const OUTCOME_LABELS: Record<string, string> = {
  correct: "Correct", correct_refusal: "Correctly refused", false_refusal: "Refused wrongly", wrong_answer: "Wrong or partial", unsupported_answer: "Invented answer", error: "Error",
};
export const MODE_LABELS_FLOW: Record<string, string> = { rag: "Model 2 · RAG", rag_peft: "Model 3 · RAG + LoRA", rag_peft_base: "Same base, no adapter", direct: "Model 1 · no documents" };
