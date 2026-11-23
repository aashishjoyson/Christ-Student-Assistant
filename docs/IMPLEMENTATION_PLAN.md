# Implementation Plan (phased, for Claude Code)

Each phase is small enough for one focused Claude Code session and ends **green**: `/verify` passes
(ruff, pytest, frontend build, secret scan). Run a phase with `/phase <n>`. Commit after each phase.

Legend: [x] done in the base repo · [ ] to do

---

## Phase 0 - Foundation (DONE in this base repository)

- [x] Repo layout, `CLAUDE.md`, skills (`/phase`, `/verify`, `/guardrails`, `/package`), `.claude/settings.json`
- [x] Settings (`app/core/config.py`) with every env var; `.env.example`
- [x] Pure domain core: intents, model modes, prompts, chunking, citations, notification policy, tokens, masking, redaction, email template, pricing
- [x] SQLite models (applicants, applications, interviews, notification_events, ingested_files, sync_runs) with UTC enforcement; seed from CSV
- [x] Fixed repository functions; reserve/complete notification
- [x] One OpenAI-compatible chat client + factory (Models 1/2 shared, Model 3 separate, no fallback)
- [x] LangGraph state, pure routing, 15 nodes, builder with checkpointer
- [x] API: health, chat, applicant verify (rate-limited), admin status; error mapping
- [x] JSONL tracing with redaction; console (simulated) email provider writing to `storage/outbox/`
- [x] React UI: model selector with "Not configured", chat, citations, Model 1 notice, action chips, workflow path, verify panel
- [x] Synthetic applicants, synthetic sample docs, synthetic eval sets
- [x] Unit tests (60, passing) + integration tests for all 12 required behaviours (written; run them first in Phase 1)
- [x] Scripts: seed, export graph diagram, secret scan, package

**Known state:** retrieval uses `NullRetriever` (Model 2/3 answer "no documents indexed"); Drive sync returns 501; SMTP not implemented.

---

## Phase 1 - Install, run the integration suite, make Model 1 real

**Goal:** a working app with a real hosted model and all tests green on your machine.

Tasks (status as of 2026-11-23)
- [x] 1. Create venv, install `requirements-dev.txt`, run `pytest`; `pip freeze` -> `backend/requirements.lock`.
      90 tests pass (60 unit + 29 integration + 1 new). Integration tests needed no changes. SQLAlchemy is pinned to
      2.0.58 because Windows Application Control blocked 2.1.9's compiled files (see `TECHNICAL_REFERENCES.md`).
- [x] 2. `cd frontend && npm install && npm run build` - green, no TypeScript errors.
- [x] 3. Verify the OpenAI chat model ID (`gpt-6-luna`, checked 2026-11-23) and set it in `.env`. With the updated key,
      Model 1 returned a real `gpt-6-luna` answer with the "not grounded" notice over HTTP (148 in / 74 out tokens,
      ~2.2 s, ~$0.00005) and a trace line was written. A human click-through of the UI is still worth doing.
- [x] 4. Reasoning model: no `empty_completion` occurred with the configuration in use, so no tuning was needed. The
      recommendation (`LLM_REASONING_EFFORT=low`, `LLM_MAX_OUTPUT_TOKENS=4000`) stays as a safeguard for longer answers.
- [x] 5. `python scripts/export_graph_diagram.py` -> `docs/graph.mmd` (15 nodes) committed.
- [x] Also: seeded the SYNTHETIC DB (10 applicants); fixed seeding on a clean checkout (`storage/` missing);
      ruff clean; declared `tzdata` for Windows; `check_secrets.py` tolerates a git-ignored root `.env`.

Acceptance: all tests pass [x]; `/api/health` shows Models 1/2 configured [x]; a real Model 1 answer with notice [x];
trace line written [x]. **Phase 1 is complete.**

---

## Phase 2 - RAG over a local folder (parsers, embeddings, Chroma, sync engine)

**Goal:** Model 2 answers the synthetic questions with citations.

Create
- `app/rag/parsers.py` - `parse(content: bytes, mime_type: str, name: str) -> list[ParsedSection]`: PDF via `pypdf` (one section per page, `page=n`), DOCX via `python-docx` (split at headings, `section=heading`), Markdown (split at `#` headings), TXT (single section). Unsupported -> raise `UnsupportedFileType`.
- `app/rag/embeddings.py` - `Embedder` protocol + `OpenAIEmbedder` (batch of <= 100 inputs, records token usage).
- `app/rag/vector_store.py` - `ChromaStore` (PersistentClient at `CHROMA_PERSIST_DIR`, collection with `{"hnsw:space": "cosine"}` and embedding-model metadata; `upsert(chunks, vectors, metadata)`, `delete_version(source_file_id, keep_version)`, `delete_file(source_file_id)`, `query(vector, k)`, `count()`).
- `app/rag/retriever.py` - `ChromaRetriever(embedder, store)` implementing `Retriever` (`ready` = `count() > 0`).
- `app/rag/sources/local_folder.py` - `LocalFolderSource(path)` implementing `DocumentSource` (id = relative path, checksum = file SHA-256, mime by extension).
- `app/rag/ingest.py` - `IngestionService(source, embedder, store, session_factory, settings).sync(trigger)` implementing ARCHITECTURE section 6 (skip unchanged, new-version-then-delete-old, keep-last-good on failure, deletions, `sync_runs` row, single-flight lock).
- `POST /api/admin/local/sync` and `scripts/sync_local_once.py`.
- `container.build_retriever()` returns `ChromaRetriever` when the collection has documents.

Tests (`tests/integration/test_ingestion.py`, fake embedder + temp dirs)
- unchanged re-sync -> 0 embed calls, identical chunk ids/count (AC-06.1)
- modified file -> only new version present (AC-06.2)
- embed failure on update -> old chunks still returned by retriever; row `failed` with error (AC-06.3)
- deleted file -> chunks gone, row `deleted` (AC-06.4)
- unsupported extension -> row `unsupported` (AC-06.5)
- parsers keep page/section metadata (unit tests with tiny generated PDF/DOCX)

Acceptance: sync `data/sample_docs`; Model 2 answers a01-a16 with citations in the UI; u01-u05 get "could not find".

---

## Phase 3 - Google Drive source, polling, admin sync

Create
- `app/rag/sources/google_drive.py` - `GoogleDriveSource` (service account or OAuth per `GOOGLE_DRIVE_AUTH_MODE`; scope `drive.readonly`; paginated `files.list` with the query/fields in ARCHITECTURE 6.3; `files.get_media` for binaries; `files.export` for Google Docs -> DOCX; `webViewLink` as `source_url`; retries with backoff on 429/5xx).
- `app/rag/poller.py` - asyncio task started in lifespan when `DRIVE_POLL_ENABLED=true`; runs `IngestionService.sync("poll")` in a thread every `DRIVE_SYNC_INTERVAL_SECONDS`; never overlaps (lock).
- Implement `POST /api/admin/drive/sync` (202 + SyncRun); `scripts/sync_drive_once.py`; `scripts/drive_oauth_login.py` (OAuth mode only).
- Follow `docs/SETUP_DRIVE.md`.

Tests: `GoogleDriveSource` with a fake Drive service object (list pagination, Google Doc export path, trashed exclusion, md5/version mapping); poller does not overlap.

Acceptance: upload a new file to the folder -> appears in status after sync -> answerable in Model 2; edit it -> new version; delete it -> no longer cited.

---

## Phase 4 - Frontend completion

- Admin page (`/admin` route or tab): enter admin key (kept in memory only), show counts, last run, per-file table, "Sync now" buttons (local/Drive).
- Debug drawer for retrieved chunks (Model 2/3) behind a toggle - not shown by default.
- Model 3 states: not configured / configured / endpoint error. Disable send when the selected model is not configured.
- Add Vitest + Testing Library: selector labels, notice rendering, citations, error message for 503.
- Accessibility pass (labels, focus, contrast) and mobile layout check.

---

## Phase 5 - Real email (opt-in)

- `app/services/email/smtp.py` - `SmtpEmailProvider` (smtplib, STARTTLS, timeout 15 s, returns `sent` only when the server accepts; Message-ID as provider id).
- Factory returns it when `EMAIL_SEND_ENABLED=true` and `EMAIL_PROVIDER=smtp`; startup refuses without `EMAIL_RECIPIENT_ALLOWLIST`.
- Tests with a fake SMTP class (accepted, refused, timeout -> failed). Never connect to a real server in tests.
- Follow `docs/SETUP_EMAIL.md` (Mailtrap sandbox recommended for demos).

---

## Phase 6 - PEFT/LoRA (Colab) and the Model 3 endpoint

- `scripts/build_peft_dataset.py` - builds `data/peft/train.jsonl` / `val.jsonl` from the synthetic corpus using
  `build_rag_messages()` (answerable with `[n]` citations, unanswerable with the exact refusal sentence,
  off-topic -> scope reply). Deterministic templates; optional `--paraphrase-with-openai --max-calls N`.
  Never include applicant data. Keep eval questions out of training data (dedupe by question text).
- `notebooks/peft_lora_colab.ipynb` + `notebooks/peft_lora_colab.py` (same code) - QLoRA on
  `Qwen/Qwen3-4B-Instruct-2507`: 4-bit NF4, fp16 on T4, r=16, alpha=32, dropout 0.05, all linear proj modules,
  max length 2048, 2 epochs; save adapter + `adapter_manifest.json` (base model id + revision, dataset hash,
  hyperparameters, date); push to a private HF repo.
- `deploy/modal_vllm.py` - Modal app serving vLLM with `--enable-lora --lora-modules cu-helpdesk-lora=<repo>@<rev> --max-lora-rank 16 --api-key <secret>`; scale-to-zero.
- `scripts/check_model3_endpoint.py` - probes `/v1/models`: adapter name present and its parent equals `MODEL3_BASE_MODEL_ID`; one test chat call.
- Follow `docs/PEFT_TRAINING_AND_DEPLOYMENT.md`.

Acceptance: health shows Model 3 configured; UI answers with adapter id shown; probe passes.

---

## Phase 7 - Evaluation and LLMOps report

- `app/eval/metrics.py` (pure: fact match, citation hit, refusal detection, hit@k, disclaimer detection) + unit tests.
- `scripts/run_evaluation.py --modes direct,rag,rag_peft,rag_peft_base --set academic_synthetic [--workflow] [--mlflow] [--judge --max-judge-calls 40]`.
  Invokes the graph in-process; `rag_peft_base` uses `build_model3_client(settings, served_model=MODEL3_ABLATION_MODEL)`.
- Outputs `storage/eval/<run_id>/results.csv`, `summary.json`; workflow cases checked against expected intent/action.
- Calibrate `RAG_MAX_DISTANCE` from retrieval distances of answerable vs unanswerable questions.
- Fill `docs/MODEL_COMPARISON_TEMPLATE.md` from `summary.json` (no invented numbers).
- Optional `GET /api/admin/experiments/summary`.

---

## Phase 8 - Hardening and packaging

- Per-IP rate limit on `/api/chat`; request size limits; CORS check.
- Optional: `langgraph-checkpoint-sqlite`, Alembic, Dockerfile.
- README walkthrough with screenshots; demo script rehearsal (`README` "Demo sequence").
- `/guardrails` review of the full diff; `python scripts/package_repo.py`.

---

## Working with Claude Code

1. Open the repo folder in VS Code, start Claude Code in the integrated terminal.
2. For each phase: `/phase 2` (Claude reads this file, the PRD/ARCHITECTURE sections, plans, implements with tests).
   Use plan mode (Shift+Tab) if you want to approve the plan first.
3. After implementation: `/verify`, then `/guardrails`, then commit.
4. Keep `.env` out of the conversation - Claude Code is denied read access to it in `.claude/settings.json`.
