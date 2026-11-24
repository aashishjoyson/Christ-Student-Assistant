# Product Requirements Document - Christ University Student Helpdesk AI

| | |
|---|---|
| Version | 3.0 (supersedes the v2 starter pack; see `REVIEW_OF_STARTER_PACK.md`) |
| Date | 20 November 2026 |
| Status | Build-ready; Phase 0 implemented in this repository |
| Project type | Academic LCA activity (experiential + problem-based learning): LLM, RAG, PEFT, LangGraph, LLMOps |
| Companion docs | `ARCHITECTURE.md` (how), `IMPLEMENTATION_PLAN.md` (when), `DECISIONS.md` (why) |

---

## 1. Summary

A compact student-helpdesk prototype with one chat interface that:

1. answers academic questions using three selectable, honestly labelled model configurations;
2. keeps its document knowledge current by ingesting new or changed files from a Google Drive folder;
3. answers application-status and interview questions from a small structured database, after verification;
4. re-sends an interview email to the applicant's registered address when they report not receiving it.

The three configurations are the experimental core of the project:

| Mode id | UI label | Generator | Retrieval | PEFT |
|---|---|---|---|---|
| `direct` | Model 1 - Direct LLM | Hosted LLM (OpenAI by default) | No | No |
| `rag` | Model 2 - LLM + RAG | **Same** hosted LLM as Model 1 | Yes | No |
| `rag_peft` | Model 3 - LLM + RAG + PEFT | Open model + trained LoRA adapter on a cloud endpoint | **Same** retrieval as Model 2 | Yes |

LangGraph orchestrates every request: one deterministic router plus specialist nodes. LLMs are used only
to generate academic answers; routing, database access and email are deterministic code.

## 2. Problem

Students consult several documents (calendar, handbook, course information) and separate systems
(admissions) for routine questions. Answers are hard to find, and applicant status is structured data,
not document text. A general LLM answers fluently but cannot be trusted on institution-specific facts.
The project investigates how far retrieval and parameter-efficient fine-tuning improve grounded
answering, and how to add a safe, auditable action to a chatbot.

## 3. Goals, non-goals and success measures

### 3.1 Goals
- G1. Compare Model 1, 2 and 3 on the same questions with reproducible metrics.
- G2. Ground institutional answers in supplied documents with traceable citations; say "not found" rather than invent.
- G3. Keep the knowledge base current from Drive without re-embedding unchanged files.
- G4. Serve applicant status and interview details only to the verified applicant.
- G5. Perform one narrowly scoped action (interview email resend) safely and auditably.
- G6. Record enough telemetry (model, prompt version, latency, tokens, cost, sources, route) to explain every answer.

### 3.2 Non-goals
- Official university deployment, SSO, ERP/SIS/admissions integration, or real student data.
- Any action beyond the resend (no grade, fee, attendance, application or interview changes).
- Autonomous multi-agent systems; local LLM inference on the student's laptop.

### 3.3 Success measures (evaluated in Phase 7)
| Measure | Target |
|---|---|
| Model 2 citation correctness on answerable synthetic questions | >= 80% cite the expected source |
| Model 2/3 correct refusal on unanswerable synthetic questions | >= 80% |
| Model 1 discloses it did not check documents on institutional questions | 100% of sampled answers |
| Re-sync of unchanged Drive folder | 0 new embeddings, 0 duplicate chunks |
| Applicant workflow cases (`data/eval/workflow_cases.jsonl`) | 100% expected intent and action status |
| Emails to any address other than the registered one | 0 (hard invariant) |
| Median latency, Model 1/2 (excluding cold starts) | < 6 s |
| Adversarial suite (`data/eval/adversarial.jsonl`): critical breaches (data leak, email to another address, system-prompt leak) | 0 (hard gate) |
| Fairness audit: gap between slices (workflow correctness, refusal rate, fact match) | Reported for every run; proposed gate <= 10 percentage points, to be calibrated after the first run |

## 4. Users

- **Student / applicant** - asks questions, picks a model for demos, verifies with application ID + registered email, asks for a resend.
- **Operator (the project team)** - configures keys, Drive, the Model 3 endpoint and email; triggers sync; runs evaluation.
- **Examiner / viva panel** - inspects behaviour, traces and the comparison report.

Deployment boundary: academic prototype, synthetic applicant data only, localhost. Production would need
institutional approval, SSO, a privacy review and a data-retention policy.

## 5. Scope and priorities (MoSCoW)

| Feature | Priority | Phase |
|---|---|---|
| Chat UI with three-model selector, citations, Model 1 banner, Model 3 "Not configured" | Must | 0 (base), 4 (polish) |
| LangGraph router + typed state + checkpointed conversation history | Must | 0 |
| Model 1 and Model 2 on one hosted model; Model 3 client with no fallback | Must | 0-1 |
| Local-folder ingestion -> parse -> chunk -> embed -> Chroma; retrieval with threshold | Must | 2 |
| Google Drive polling + manual sync, change detection, deletions, keep-last-good | Must | 3 |
| Applicant DB, fixed lookups, signed session, rate-limited verification | Must | 0 |
| Interview resend workflow with reservation, cooldown, audit, simulated email | Must | 0 |
| JSONL request traces with redaction | Must | 0 |
| Evaluation runner over the synthetic set; CSV/JSON summary; comparison report | Must | 7 |
| PEFT notebook (Colab) + adapter manifest + serving recipe | Must | 6 |
| SMTP provider with allowlist (opt-in real sending) | Should | 5 |
| Admin page for sync/status | Should | 4 |
| MLflow logging of evaluation runs | Should | 7 |
| PEFT ablation (base vs adapter on the same endpoint) | Should | 7 |
| OAuth Drive auth (service account is primary) | Could | 3 |
| Optional LLM-as-judge with a hard call cap | Could | 7 |
| Alembic migrations, Docker | Could | 8 |
| LLM fallback router, Drive webhooks, multi-worker deployment | Won't (v1) | - |

## 6. Experimental design

- Models 1 and 2 use the same provider, model ID, output-token limit and history window; only retrieval differs.
- Models 2 and 3 use the same retrieval, top-k, threshold and **identical prompt** (`rag-v1`); only the generator differs.
- Model 3's backbone (small open model) differs from Models 1/2 (hosted model). Report this as a model-family
  confound. To isolate the PEFT effect, the evaluation also runs **base model + RAG** on the same endpoint
  (ablation). Comparison table columns: Model 1, Model 2, Model 3-base (ablation), Model 3.
- Decoding: hosted reasoning models may not accept `temperature`; record whatever was sent.
- Every run records provider/model/adapter IDs, prompt versions, top-k, threshold, embedding model and date.
- The adapter teaches **behaviour** (grounded format, citations, refusal, scope), never facts; facts stay in RAG.

## 7. Functional requirements and acceptance criteria

Acceptance criteria (AC) are written so each maps to an automated test where possible. Tests that already
exist in `backend/tests/` are named.

### FR-01 Chat interface
- Visible selector with the exact labels from section 1; selected mode sent with every message.
- Each answer shows who handled it (`handled_by`): model label + model ID (+ adapter ID for Model 3), "Applicant service (database lookup, no LLM)" or "Helpdesk (template, no LLM)".
- Model 1 answers show a banner: not grounded in university documents.
- Model 2/3 answers list citations (file name + page/section; link when the source URL is known). If the model cited nothing, label the list "Retrieved (not explicitly cited)".
- Model 3 shows "Not configured" in the selector when `/api/health` reports it unconfigured; a request returns a clear message, never a substitute answer.
- Conversation ID persists for the browser tab; applicant session shown with masked email.
- AC-01.1 Labels match exactly. AC-01.2 Model 3 unconfigured -> inline explanation, no answer text from another model.

### FR-02 Orchestration (LangGraph)
- Typed shared state; compiled `StateGraph` with conditional edges; in-memory checkpointer keyed by conversation ID.
- Intents: `academic_qa`, `applicant_status`, `interview_details`, `resend_interview_email`, `general_help`, `unsupported`.
- Deterministic classification; personal intents require a first-person cue or an application ID; default `academic_qa`.
- Every response includes the visited node path (shown under "How this was handled").
- AC-02.1 Routing table tests (`test_intents.py`, `test_routing.py`). AC-02.2 Applicant/email/help/unsupported paths never use an LLM to write the answer (templates only; `test_model_paths.py`, `test_applicant_and_email.py`) and make no LLM call at all when the rules recognise the message. AC-02.3 When the rules are inconclusive and the message looks personal, at most one small intent-label call is made (ADR-015); a failure or unclear label is treated as a normal question; the label cannot bypass verification, the cooldown or the registered-recipient rule (`test_intent_fallback.py`, adversarial cases adv-049..054).

### FR-03 Model 1 - Direct LLM
- System prompt forbids claiming document access and requires a disclaimer on institution-specific questions.
- No retriever call, no hidden context.
- AC-03.1 Retriever call count is 0 (`test_model1_never_calls_retriever_and_flags_ungrounded`).

### FR-04 Model 2 - LLM + RAG
- Retrieve top-k (default 4) chunks; keep those within `RAG_MAX_DISTANCE`; numbered context with source labels.
- Zero kept chunks -> deterministic "I could not find this in the available university documents" (no LLM call).
- No documents indexed -> deterministic "not indexed yet" message.
- Parse `[n]` markers into citations.
- AC-04.1 Retriever called once and citations returned (`test_model2_calls_retriever_and_returns_citations`). AC-04.2 No-evidence path makes no LLM call.

### FR-05 Model 3 - LLM + RAG + PEFT
- Same retrieval and prompt as Model 2; generator is the OpenAI-compatible endpoint serving the adapter (`MODEL3_MODEL`).
- Configured only when base URL, served model name, base model ID and adapter ID are all set.
- Not configured -> HTTP 503 `model3_not_configured`; endpoint failure -> 502/504; never a fallback.
- Responses and traces carry base model ID and adapter ID.
- Phase 6 adds an endpoint probe that checks `/v1/models` lists the adapter with the expected parent model.
- AC-05.1 `test_model3_not_configured_returns_503_and_calls_nothing`. AC-05.2 `test_model3_uses_peft_endpoint_with_same_evidence`.

### FR-06 Document ingestion (local folder, then Google Drive)
- Sources: local folder (`data/sample_docs`, Phase 2) and one Drive folder (Phase 3), non-recursive, trashed files excluded.
- Formats: PDF (page numbers), DOCX (nearest heading), TXT, Markdown (nearest heading), Google Docs (exported). Others -> status `unsupported`.
- Change detection: Drive `md5Checksum` (binary) or `version` (Google Docs) + `modifiedTime`; then SHA-256 of content - unchanged content is never re-embedded.
- Chunking: 900 chars / 120 overlap (configurable), never across sections; chunk ID `{source_file_id}:{content_version}:{index}`.
- Update order: parse -> embed -> upsert new version -> delete old version -> mark indexed. Any failure keeps the previous version and records the error.
- Deleted/trashed files: chunks removed, row marked `deleted`.
- Polling every 300 s when enabled; manual sync endpoint; single-flight lock; every run recorded in `sync_runs`.
- AC-06.1 Re-sync unchanged -> 0 embedding calls, same chunk count. AC-06.2 Changed file -> new version only. AC-06.3 Embed failure on update -> old chunks still retrievable, status `failed` with error. AC-06.4 Deleted file -> not retrievable. AC-06.5 Unsupported type reported.

### FR-07 Applicant data and verification
- Tables: `applicants`, `applications`, `interviews`, `notification_events` (+ `ingested_files`, `sync_runs`).
- 10 synthetic applicants covering: scheduled, rescheduled, cancelled, completed, no interview.
- `POST /api/demo/applicant/verify` with application ID + registered email: case-insensitive email, constant-time compare, uniform 401, 5 attempts / 15 min per IP and per application ID (429). Success returns a 30-minute signed token and a masked email.
- Fixed repository functions only, each scoped by the verified `applicant_id`. No name search, no LLM SQL.
- AC-07.1..7.5 in `test_applicant_and_email.py` (success, uniform failure, rate limit, own record only, cross-applicant scoping).

### FR-08 Interview email resend
- Trigger: verified applicant + resend intent ("I have not received my interview email"). No extra confirmation (narrow, system-parameterised action).
- Graph path: `verify_identity -> fetch_interview_details -> check_resend_eligibility -> send_interview_email -> record_notification -> compose_applicant_response`.
- Eligibility: active interview (`scheduled`/`rescheduled`) in the future; valid recipient; no pending/sent/simulated event in the last 15 min; at most 3 per 24 h; when real sending is enabled, recipient must match `EMAIL_RECIPIENT_ALLOWLIST`.
- Reservation: insert `pending` event with a UNIQUE window key before sending; failed sends release the key.
- Recipient and every email field are re-read from the database inside the send node; any address in the message is ignored.
- Statuses: `simulated` (console provider), `sent` (provider accepted), `failed`, `not_eligible`. UI shows the status and masked recipient.
- AC-08.1..8.7 in `test_applicant_and_email.py` (registered recipient only, simulated audit row, cooldown, failure audit + retry, provider exception, ineligible interviews, allowlist).

### FR-09 LLMOps and evaluation
- JSONL trace per request: timestamp, hashed conversation ID, intent + rule, requested mode, handled_by, provider, model, base/adapter IDs, prompt version, tokens, estimated cost, latencies, retrieval counts, chunk IDs, cited sources, action status, error code, node path. No message text unless `TRACE_INCLUDE_TEXT=true` (then redacted; applicant answers never).
- Evaluation runner (Phase 7) over `data/eval/*.jsonl` for selected modes: answer, citations, latency, tokens, cost; deterministic metrics (fact match, citation hit, refusal correctness, retrieval hit@k); human-review columns for relevance/faithfulness; optional capped LLM judge.
- Output: `storage/eval/<run_id>/results.csv`, `summary.json`, and a filled `MODEL_COMPARISON_TEMPLATE.md`. Optional MLflow run.

### FR-10 Admin utilities
- `GET /api/admin/drive/status`, `POST /api/admin/drive/sync` (Phase 3), seed script, secret scan, packaging script.
- Admin routes require `X-Admin-Key` and are disabled until `ADMIN_API_KEY` is set to a non-placeholder value. Local use only.

### FR-11 Health
- `GET /api/health`: per-model configuration (label, provider, model, adapter), retriever readiness, email mode, Drive configuration. No secrets.

### FR-12 Evaluation, monitoring and validation with Evidently (Phase 7)
Evidently (Apache-2.0, https://github.com/evidentlyai/evidently) is the offline evaluation and reporting engine. It is never imported by the request path.
- **Prompt and response monitoring:** row-level descriptors (length, refusal, disclaimer, citation validity, PII, optional toxicity/relevance/faithfulness) and trace-metadata reports with tests; trends in a local Evidently workspace.
- **Adversarial and edge-case testing:** a committed synthetic adversarial set run through the real graph; 0 critical breaches is a hard gate.
- **RAG evaluation:** retrieval quality (hit@k, MRR, source recall, context relevance) and answer faithfulness/completeness/correctness against the retrieved context; Model 2 vs Model 3 vs ablation on identical context.
- **Pre-deployment validation:** candidate vs baseline reports with pass/fail thresholds, data-quality checks on the evaluation sets (no eval question in PEFT training data), run in CI before a prompt, model or adapter change is accepted.
- **Bias and fairness audit:** the same report per slice (programme, interview mode, language style, name-only paraphrase pairs) with gap thresholds and stated limits.
- LLM judges are optional, capped (`--max-judge-calls`), configurable and never used in tests; evaluation data is synthetic.
- AC-12.1 Offline Evidently report built from a fake-LLM run. AC-12.2 A degraded fake run fails a threshold test. AC-12.3 Adversarial suite: 0 critical breaches. AC-12.4 Paraphrase-parity test passes (names never change intent/action). AC-12.5 CI blocks a change that breaks a gate.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Simplicity | One FastAPI process, one React app, SQLite, embedded Chroma. No queues, no microservices. |
| No local LLM | Only hosted APIs and the remote Model 3 endpoint. Embeddings via API. |
| Reliability | Explicit timeouts (30 s hosted, 90 s Model 3 for cold starts), SDK retries with backoff for 429/5xx, clear error codes. |
| Security | Secrets only in `.env`; secret scan before commit/package; admin key; signed applicant tokens; allowlisted real email. |
| Privacy | Synthetic data; masked emails in UI/logs; no message text in traces by default; applicant answers excluded from LLM memory. |
| Transparency | `handled_by`, notices, citations and node path on every answer. |
| Reproducibility | Bounded dependency ranges + lock file; prompt versions; recorded model IDs; seeded relative dates. |
| Cost | No LLM for routing/applicant/help; short prompts; top-k 4; deterministic no-evidence answers; no default judge. |
| Teachability | Pure domain module with unit tests; small explicit nodes; every rule explainable in a sentence. |

## 9. API (summary; full contracts in ARCHITECTURE section 9)

`GET /api/health` · `POST /api/chat` · `POST /api/demo/applicant/verify` · `GET /api/admin/drive/status` ·
`POST /api/admin/drive/sync` · `POST /api/admin/local/sync` (Phase 2) · `GET /api/admin/experiments/summary` (Phase 7, optional)

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hosted model deprecated during the project | High | Config-only model ID; record IDs per run; re-run eval if changed. |
| Model 3 endpoint cost/cold starts | Medium | Scale-to-zero, warm-up call before demos/eval, free credits, stop after use. |
| Colab GPU unavailable or session limits | Medium | 4B QLoRA fits a T4; checkpoint to Drive; fall back to Qwen3-1.7B. |
| Drive OAuth token expiry (Testing apps: 7 days) | Medium | Service account recommended; OAuth caveat documented. |
| Real documents contain prompt-injection text | Low | Context treated as data in the prompt; no tools exposed to the LLM. |
| Synthetic eval overstates quality | Medium | Add real-document questions via the template once documents are indexed. |

## 11. Assumptions and inputs from the team

Academic calendar, handbook and course documents (uploaded to Drive); OpenAI key; optional OpenRouter key;
Google Cloud project for Drive; Hugging Face account (adapter storage); Modal or similar account for Model 3;
SMTP/test-inbox credentials only if real email is demonstrated. None of these block Phases 0-2.

## 12. Glossary

RAG - retrieval-augmented generation. PEFT - parameter-efficient fine-tuning. LoRA - low-rank adapter
weights trained on top of a frozen base model. QLoRA - LoRA trained on a 4-bit quantised base. vLLM - an
inference server that can serve a base model and LoRA adapters through an OpenAI-compatible API.
Checkpointer - LangGraph persistence keyed by thread (conversation) ID.
