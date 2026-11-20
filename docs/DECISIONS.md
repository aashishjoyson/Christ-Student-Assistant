# Architecture Decision Records

Short records of the choices most likely to be questioned in a viva. Format: context -> decision -> consequences.

## ADR-001 LangGraph router with deterministic specialists, not a multi-agent swarm
- **Context:** The brief requires LangGraph and agentic workflows, with tight cost and safety limits.
- **Decision:** One compiled `StateGraph`: a deterministic `classify_intent` router, deterministic nodes for
  identity/DB/email, and LLM calls only in the three answer nodes.
- **Consequences:** Every path is testable without an LLM; most requests cost nothing; the email workflow is an
  explicit, auditable path. Trade-off: no free-form "agent" behaviour - deliberately.

## ADR-002 Deterministic intent rules; no LLM router in v1
- **Decision:** Regex rules with a first-person requirement for personal intents; default to `academic_qa`.
- **Consequences:** Zero routing cost, explainable rules, unit-tested table. Misroutes fall to academic Q&A
  (safe: no private data, no action). An LLM fallback can be added later behind a flag.

## ADR-003 Same hosted model for Models 1 and 2; same retrieval and prompt for Models 2 and 3
- **Decision:** One `primary_llm` client instance serves both Model 1 and 2; Models 2 and 3 share
  `retrieve_context` and the `rag-v1` prompt.
- **Consequences:** Model 1 vs 2 isolates RAG; Model 2 vs 3 isolates the generator. The backbone difference
  in Model 3 is handled by the ablation (ADR-009).

## ADR-004 Chat Completions API through one OpenAI-compatible client
- **Context:** OpenAI recommends the Responses API for new projects, but OpenRouter and vLLM implement Chat
  Completions as the common interface.
- **Decision:** All three paths call `chat.completions.create` via `OpenAICompatibleChatClient`.
- **Consequences:** One client, one request shape, one set of error mappings; Model 3 is a configuration, not
  new code. We forgo Responses-only features (not needed here).

## ADR-005 Functional core (`app/domain`) with stdlib-only modules
- **Decision:** Safety-relevant rules (intents, eligibility, tokens, masking, chunking, prompts, citations) are
  pure functions with no framework imports.
- **Consequences:** Fast unit tests that run anywhere; rules are readable in isolation for the viva.

## ADR-006 In-memory checkpointer for conversation history
- **Decision:** `InMemorySaver`, `thread_id = conversation_id`.
- **Consequences:** Demonstrates LangGraph persistence with no extra service. History resets on restart.
  Swap for `langgraph-checkpoint-sqlite` if persistence across restarts becomes a requirement.

## ADR-007 Signed applicant session token instead of per-message credentials
- **Decision:** Verify once (ID + email), receive a 30-minute HMAC token, send it per request; the
  `verify_identity` node validates signature, expiry and existence.
- **Consequences:** No PII in chat payloads or graph state; tokens cannot be forged without `APP_SECRET_KEY`.
  Still prototype-grade: production needs SSO.

## ADR-008 Reserve-then-send with a UNIQUE window key
- **Decision:** Readable policy check + `notification_events` row inserted as `pending` with a UNIQUE
  idempotency key derived from the interview and cooldown window, before calling the provider.
- **Consequences:** Concurrent duplicates are impossible at the database level; every attempt is audited;
  failed sends release the key so the student can retry.

## ADR-009 Model 3 on vLLM with LoRA; ablation on the same endpoint
- **Context:** Per-token serverless LoRA hosting largely disappeared in 2026; GPU endpoints with
  scale-to-zero are the practical option. vLLM serves a base model and named LoRA adapters through an
  OpenAI-compatible API.
- **Decision:** Base model `Qwen/Qwen3-4B-Instruct-2507` (Apache-2.0, non-thinking variant, fits a Colab T4 for
  QLoRA). Serve with vLLM `--enable-lora` on Modal (recommended) or HF Inference Endpoints. Evaluate both
  `model=<adapter>` and `model=<base>` on the same endpoint.
- **Consequences:** Real adapter, verifiable via `/v1/models`; a controlled PEFT ablation at no extra cost;
  GPU time must be budgeted and the endpoint stopped after use.

## ADR-010 Local-folder source before Google Drive
- **Decision:** A `DocumentSource` protocol with `LocalFolderSource` (Phase 2) and `GoogleDriveSource` (Phase 3).
- **Consequences:** The sync state machine (skip/update/keep-last-good/delete) is built and tested without
  Google credentials; Drive becomes a thin adapter.

## ADR-011 Service account as the default Drive auth
- **Context:** OAuth apps in "Testing" publishing status receive refresh tokens that expire after 7 days,
  which silently breaks unattended polling.
- **Decision:** Default `GOOGLE_DRIVE_AUTH_MODE=service_account` (share the folder with the service account as
  Viewer); OAuth desktop flow supported as an alternative.
- **Consequences:** No browser step and no weekly re-consent. Some Workspace domains block sharing with
  external service accounts; then use OAuth and accept the caveat.

## ADR-012 JSONL traces always; MLflow optional for evaluation runs
- **Decision:** Every request writes a redacted JSONL line. MLflow (>= 3.7, SQLite backend) logs evaluation
  runs only, via `requirements-mlops.txt`.
- **Consequences:** The app has no observability dependency; evaluation results are still comparable in the
  MLflow UI when wanted.

## ADR-013 Templates for applicant, help and fallback answers
- **Decision:** No LLM writes applicant-facing factual text; templates render database fields.
- **Consequences:** Zero hallucination risk and zero cost on these paths; `handled_by` labels stay truthful.
