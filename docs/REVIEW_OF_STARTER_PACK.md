# Review of the v2 starter pack (CLAUDE_BUILD_PROMPT.md, PRD.md, ARCHITECTURE.md)

Reviewed 20 November 2026. This document explains what was kept, what was changed and why, so the
v3 PRD and architecture in this repository can be defended in a viva.

## Verdict

The v2 pack is strong on **intent and guardrails**: three honestly labelled model paths, LangGraph as a
router with deterministic specialist nodes instead of an agent swarm, no LLM-generated SQL, recipient only
from the database, simulated email by default, no silent Model 3 fallback. All of that is kept.

Its weaknesses are **contradictions between files, a few real security gaps, unstated numbers, and a
delivery model that does not suit Claude Code**: a single 400-line prompt asking for research, the whole
build, tests and packaging in one pass tends to produce shallow code across many features. v3 resolves
the contradictions, closes the gaps and splits the build into nine phases with tests per phase.

## What the pack gets right (kept as-is)

- Model 1 and Model 2 share one provider and model ID, so RAG is the only difference between them.
- Model 3 must load a real adapter and must fail with 503 rather than substitute another model.
- Applicant data via fixed parameterized functions; no name-only lookup; synthetic data only.
- Email workflow as a visible graph path with eligibility, idempotency, cooldown and an audit table.
- "Keep last known-good chunks if an update fails", deterministic chunk IDs, no re-embedding of unchanged files.
- Cost discipline: no LLM call to route obvious intents, no LLM-as-judge by default.
- Honest experimental framing (model-family confound acknowledged).

## Issues found and how v3 resolves them

Severity: **H** = would cause a security/correctness defect or invalid results; **M** = would cause
rework or confusion; **L** = polish.

| # | Sev | Issue in v2 | Resolution in v3 |
|---|-----|-------------|------------------|
| 1 | H | **Applicant identity was never bound to a session.** The verify endpoint and the graph's `verify_applicant` node were described separately; either the student re-sends their email on every message or identity is stored under a client-chosen conversation ID (hijackable). | Verify endpoint issues a short-lived **HMAC-signed session token** (applicant id + expiry, no PII). Chat sends it in `X-Applicant-Session`; the `verify_identity` node validates it every turn. (ADR-007) |
| 2 | H | **Verification is enumerable.** ID + email with no throttling or uniform errors lets anyone probe IDs and emails. | Same 401 message for unknown ID and wrong email, constant-time compare, sliding-window rate limit per IP and per application ID (429). |
| 3 | H | **Conversation memory could leak applicant data.** If applicant answers enter LLM history, a later "repeat what you said" in Model 1/2 can echo them, and anyone continuing that thread could read them. | Applicant-service answers are stored in history as a placeholder; server issues unguessable UUID conversation IDs; recipient emails never enter graph state. |
| 4 | H | **Default chat model will be shut down mid-project.** The pack left `OPENAI_CHAT_MODEL` blank; the obvious choice (`gpt-5-mini`/`gpt-5-nano`) is retired from the OpenAI API on 11 Dec 2026, and the `gpt-4o-mini`/`gpt-4.1-mini` snapshots on 14 Jan 2027. | `.env.example` defaults to `gpt-6-luna` (OpenAI's recommended low-cost replacement), with an instruction to verify the ID; all IDs live in one settings object and are recorded in every trace. |
| 5 | H | **Experimental confound can be reduced cheaply but the pack only disclaims it.** | Same prompt (`rag-v1`) and same retrieval for Models 2 and 3, plus an evaluation-only **ablation**: the Model 3 vLLM endpoint serves the *base* model and the adapter side by side, so "base + RAG" vs "base + LoRA + RAG" isolates the PEFT effect at no extra infrastructure cost. (ADR-009) |
| 6 | H | **Race condition in duplicate-email prevention.** "Check history, then send" lets two simultaneous requests both pass. Idempotency key format was undefined. | Two layers: readable policy check, then a **reservation row with a UNIQUE window key** (`sha256(interview_id, cooldown window)`), committed before sending. Failed sends release the key so retry is possible. Cooldown 15 min, max 3/day, configurable. |
| 7 | H | **"Report sent only after provider confirmation" is ambiguous** - SMTP acceptance is not delivery. | Status `sent` is defined as "accepted by the provider"; UI text says "sent", never "delivered". |
| 8 | H | **Real-send safety had no hard guard.** One misconfigured `.env` plus imported real data could email real people. | Real sending requires `EMAIL_RECIPIENT_ALLOWLIST`; non-allowlisted recipients are `not_eligible`. Startup refuses SMTP without an allowlist. |
| 9 | M | **Node names, intents and UI labels differ between files** (`direct_llm_answer` vs `baseline_answer`, `hybrid_answer`; PRD selector labels `LLM`, `LLM + RAG` vs prompt's `Model 1 - Direct LLM`). "Hybrid" also usually means hybrid *search*, which is misleading. | One canonical set: modes `direct` / `rag` / `rag_peft`, labels `Model 1 - Direct LLM` etc., node names fixed in ARCHITECTURE section 4 and in code. |
| 10 | M | **`general_help -> direct_llm_answer` mislabels answers.** In Model 3 mode a greeting would be answered by OpenAI while the UI says Model 3. Applicant answers would also be labelled with the selected model even though no LLM ran. | Greetings/help and unsupported requests use templates (no LLM). Every response carries `handled_by` (LLM + model/adapter, applicant service, or helpdesk template), so labels are always truthful. |
| 11 | M | **An LLM router "when needed" invites a hidden cost on most messages.** | Deterministic rules with a first-person requirement for personal intents; default is `academic_qa`. LLM fallback routing is a documented "Won't (v1)". |
| 12 | M | **"OpenRouter as fallback" breaks the Model 1 vs 2 comparison** if it silently switches models on an OpenAI error. | OpenRouter is a *provider choice* (`LLM_PROVIDER`) for Models 1 and 2 together, never an automatic fallback. |
| 13 | M | **Evaluation cannot run without real documents**, yet fabricated university facts are forbidden. | A clearly fictional sample corpus (`data/sample_docs/SYNTHETIC_*`, "Northwind Institute (fictional)") with a 21-question synthetic eval set, plus a template for real-document questions once Drive is configured. |
| 14 | M | **Drive change detection under-specified.** Google Docs have no `md5Checksum`; OAuth apps in "Testing" status get refresh tokens that expire after 7 days, which silently breaks polling. | Binary files: `md5Checksum`; Google Docs: `version`; plus SHA-256 of downloaded content to skip re-embedding when only metadata changed. Service account (folder shared with it) is the recommended auth; OAuth documented with the 7-day caveat. Env var renamed from `GOOGLE_APPLICATION_CREDENTIALS` (which Google libraries auto-read as ADC) to `GOOGLE_DRIVE_CREDENTIALS_FILE`. |
| 15 | M | **In-process polling duplicates under `--reload` or multiple workers.** | Poller off by default (`DRIVE_POLL_ENABLED`), single-flight DB lock, one worker documented. |
| 16 | M | **Ingestion is untestable without Google.** | `DocumentSource` interface: `LocalFolderSource` (Phase 2) and `GoogleDriveSource` (Phase 3) share one sync engine, so the state machine is tested on a local folder first. |
| 17 | M | **Retrieval "no suitable evidence" had no definition.** | Cosine-distance threshold `RAG_MAX_DISTANCE` (calibrated in Phase 7); zero passing chunks returns a deterministic "not found" answer without an LLM call. |
| 18 | M | **Reasoning-model API gotchas not covered.** GPT-5-family models reject `temperature`, need `max_completion_tokens`, and can return empty text when reasoning consumes the token budget. | Client sends optional params only when configured, uses the right token parameter per provider, and turns empty completions into a clear error. |
| 19 | M | **PEFT train/serve format mismatch risk** and an unrealistic serving assumption. Per-token serverless LoRA hosting has largely disappeared in 2026 (Together discontinued it; Fireworks' serverless preview is limited). | Training data is generated with the app's own `build_rag_messages()`. Recommended serving: vLLM with `--enable-lora` on Modal (scale-to-zero, $30/month free credit on the Starter plan), with HF Inference Endpoints and CoreWeave/W&B serverless LoRA as alternatives. Base model: `Qwen/Qwen3-4B-Instruct-2507` (Apache-2.0, non-thinking, fits a Colab T4 with QLoRA). |
| 20 | M | **MLflow file store** (`./mlruns`) is deprecated; recent MLflow raises unless explicitly allowed. | MLflow optional (`requirements-mlops.txt`), used for evaluation runs only, default `sqlite:///storage/mlflow.db`; JSONL traces always on. |
| 21 | M | **openai-python 3.x no longer installs `httpx`**, which FastAPI's TestClient needs; HTTP-level mocks of the SDK are fragile. | `httpx` pinned in dev requirements; tests fake the `ChatClient` protocol instead of HTTP. |
| 22 | M | **One-shot mega prompt** mixes requirements, design and process, forbids asking questions, and demands ZIP packaging in the same pass. | `CLAUDE.md` (short, persistent rules) + PRD (what) + ARCHITECTURE (how) + IMPLEMENTATION_PLAN (nine phases with acceptance tests) + `/phase`, `/verify`, `/guardrails`, `/package` skills. |
| 23 | L | Duplicate PRD in `.md`, `.docx`, `.pdf` - three sources of truth. | Markdown only, in `docs/`. |
| 24 | L | Timezone, data retention, CORS, and admin defaults unspecified. | UTC storage with an enforcing column type, `APP_TIMEZONE=Asia/Kolkata` for display; traces contain no message text by default; admin routes disabled until `ADMIN_API_KEY` is set to a non-placeholder. |
| 25 | L | No MoSCoW prioritisation, so everything looks equally mandatory. | PRD section 5 prioritises every feature. |

## Scope warnings worth knowing

- **Model 3 costs money to serve** (GPU time) even with scale-to-zero. Budget the evaluation run
  (~1-2 GPU hours) and stop the endpoint afterwards. Free credits usually cover it.
- **Real university documents** may be copyrighted or internal. Keep them in Drive only; the ZIP and Git
  history must never contain them.
- **"Automatic resend without confirmation"** is acceptable *only* because recipient, content and frequency
  are all fixed by the system. Do not extend this pattern to any action with user-controlled parameters.
