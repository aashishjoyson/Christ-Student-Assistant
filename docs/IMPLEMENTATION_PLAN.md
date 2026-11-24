# Implementation Plan (phased, for Claude Code)

Each phase is small enough for one focused Claude Code session and ends **green**: `/verify` passes
(ruff, pytest, frontend build, secret scan). Run a phase with `/phase <n>`. Commit after each phase.

Legend: [x] done in the base repo · [ ] to do

## Status board (2026-11-24)

| Phase | Status | Next step / what it needs from you |
|---|---|---|
| 0 Foundation | Done | - |
| 1 Install, tests, Model 1 live | **Done** (committed + pushed, 90 tests, Model 1 verified live) | - |
| UI restyle (widget on a homepage backdrop) | In progress, **uncommitted** | Real photos still to add (see Phase 4); then commit |
| 2 RAG over a local folder | **Done, verified live on the real documents** (committed + pushed) | Next: automatic ingestion (poller) and the Drive source = Phase 3 |
| 3 Google Drive source | Not started | Google Cloud project, service account, shared Drive folder ID |
| 4 Frontend completion | Partly (restyle) | Admin page, debug drawer, Vitest, accessibility pass |
| 5 Real email (opt-in) | Not started | Optional: SMTP sandbox (Mailtrap) credentials + allowlist |
| 6 PEFT/LoRA + Model 3 endpoint | Not started | Hugging Face account, Colab GPU session, Modal (or HF Endpoints) account |
| 7 Evaluation, monitoring, validation (**Evidently**) | **7.0 done; 7.3 adversarial suite and 7.6 phrasing/name parity done** (Evidently reports verified in a throwaway venv; not yet in `backend/.venv`) | Next: 7.1 runner (needs `pip install -r backend/requirements-eval.txt`), 7.2, 7.4 (after Phase 2), 7.5 CI |
| 8 Hardening, CI, packaging | Not started | GitHub Actions CI is specified in 7.5 |

## LLMOps roadmap: what we do next, and why

This project is an LLMOps case study: one real RAG system taken round the whole loop.

```text
 data  ->  index  ->  prompt / model  ->  serve  ->  observe  ->  evaluate  ->  gate  ->  improve
(Drive)  (Chroma)    (versioned)        (SSE API)   (traces)    (Evidently)   (CI)    (prompts, LoRA)
```

**Already in place:** prompt versions and model ids in every trace; token, cost, latency and time-to-first-word tracking; a redacted trace log;
a versioned, idempotent ingestion engine; an adversarial suite (0 critical breaches) and a fairness audit with accepted baselines; ADRs;
locked dependencies; secret scanning; a CI-safe fake-LLM test harness (300 tests).

| # | Milestone | LLMOps concept | What gets built | Needs from you |
|---|---|---|---|---|
| M1 | **Automatic ingestion** (Phase 3) | data pipelines, freshness, lineage | `GoogleDriveSource`, a source-agnostic poller (never overlapping), per-file status and "last synced" in the admin API, failure alerts in the log, index versioning rules | Google Cloud setup (`docs/SETUP_DRIVE.md`), folder ID, key file |
| M2 | **Evaluation harness + golden set** (7.1, 7.4) | experiment tracking, offline evaluation, reproducibility | `run_evaluation.py` with a run id and a frozen config snapshot (git sha, prompt versions, model ids, embedding model, chunk settings); retrieval hit@k and MRR, citation correctness, refusal correctness, optional capped LLM-judge faithfulness; calibrate `RAG_MAX_DISTANCE`; Evidently reports | 20-30 real questions with expected facts (I draft candidates from your documents; you approve) |
| M3 | **CI/CD and promotion gates** (7.5) | continuous evaluation, regression gates, promotion policy | GitHub Actions: lint + tests + build + secrets + eval gate against a baseline; rules for when a prompt, model or adapter may replace the current one; branch protection | nothing (optional repo secret for a capped live run) |
| M4 | **Monitoring and feedback loop** (7.2) | observability, drift, human feedback | thumbs up/down in the chat linked to the trace id; dashboards for p50/p95 latency, time to first word, cost per answer, refusal and no-evidence rate, retrieval-distance drift, intent mix; alert thresholds; opt-in persistent chat history | nothing |
| M5 | **Fine-tuning operations** (Phase 6) | dataset versioning, model registry, ablation, controlled rollout | PEFT dataset builder with eval-leak checks, Colab QLoRA notebook, adapter manifest in a private Hugging Face repo, vLLM endpoint on Modal, Model 3 vs base ablation, promotion through the M3 gate | Hugging Face, Colab and Modal accounts |
| M6 | **Hardening and delivery** (Phase 4/8) | deployment, security, governance | admin page, Docker, rate limits and access control, retention rules, model card and the final comparison report | - |

**Order:** M1 -> M2 -> M3 -> M4 -> M5 -> M6. M1 can start now: the Drive source is built and tested against a fake Drive service first, so the Google setup runs in
parallel and is only needed for the first live sync. M2 depends on the golden set, which is the only part that needs your domain knowledge.


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

**Status 2026-11-24: DONE.** Built as specified (parsers, embeddings, Chroma store, retriever, local source, sync engine, `POST /api/admin/local/sync`,
`GET /api/admin/local/status`, `scripts/sync_local_once.py` with `--dry-run`, container wiring) plus these deliberate additions:
- **XLSX and CSV parsers** (the real course table is a spreadsheet). Each row is one section; its short cells (course, campus, ...) are a **prefix repeated in every
  chunk** of that row (`ParsedSection.prefix`), so a chunk from the middle of a long "Fees" cell still names its course.
- **`LOCAL_DOCS_INCLUDE_SYNTHETIC` (default false):** `SYNTHETIC_*` placeholder files are NOT indexed. Found live: with them in the same folder the assistant answered
  real exam-date questions from invented dates. The synthetic evaluation set must opt in and use its own `CHROMA_COLLECTION` (Phase 7.4).
- Chroma anonymous telemetry is off; `package_repo.py` and `.gitignore` keep real documents out of git and ZIPs.
- Tests: 100 new (parsers, embedder batching, chunk prefix, and the sync state machine AC-06.1 to 06.5 against a real temporary Chroma with a fake embedder).
- Live result on the real documents: 4 files (calendar PDF, handbook PDF, course XLSX, website FAQ) -> 1,985 chunks; 380k tokens, about $0.0076; a second sync made 0 embedding calls.
- Not done here (by design): synthetic-set acceptance (a01-a16 / u01-u05) belongs to 7.4; the admin page to Phase 4; the poller and Drive to Phase 3.

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

**Automatic ingestion = this phase.** The poller is source-agnostic: it just calls `IngestionService.sync("poll")` every `DRIVE_SYNC_INTERVAL_SECONDS` (single-flight,
never overlapping). It can be built first and used with the local folder today; switching to Drive then only swaps the `DocumentSource`. A new, edited or deleted file shows up
within one polling interval (default 5 minutes); instant push needs a public HTTPS endpoint, which a local prototype does not have.

Create
- `app/rag/sources/google_drive.py` - `GoogleDriveSource` (service account or OAuth per `GOOGLE_DRIVE_AUTH_MODE`; scope `drive.readonly`; paginated `files.list` with the query/fields in ARCHITECTURE 6.3; `files.get_media` for binaries; `files.export` for Google Docs -> DOCX; `webViewLink` as `source_url`; retries with backoff on 429/5xx).
- `app/rag/poller.py` - asyncio task started in lifespan when `DRIVE_POLL_ENABLED=true`; runs `IngestionService.sync("poll")` in a thread every `DRIVE_SYNC_INTERVAL_SECONDS`; never overlaps (lock).
- Implement `POST /api/admin/drive/sync` (202 + SyncRun); `scripts/sync_drive_once.py`; `scripts/drive_oauth_login.py` (OAuth mode only).
- Follow `docs/SETUP_DRIVE.md`.

Tests: `GoogleDriveSource` with a fake Drive service object (list pagination, Google Doc export path, trashed exclusion, md5/version mapping); poller does not overlap.

Acceptance: upload a new file to the folder -> appears in status after sync -> answerable in Model 2; edit it -> new version; delete it -> no longer cited.

---

## Phase 4 - Frontend completion

**Done early (2026-11-24):** homepage-widget redesign with the Christ University crest, streamed answers, safe markdown rendering, citation chips, follow-up-aware retrieval, "New chat", conversation restored after a refresh, `npm test` for the parsers. **Still open:** admin page, debug drawer, Vitest + Testing Library, accessibility pass and a mobile check. The homepage photos are AI-generated illustrations (see LICENSE_NOTES.md); swap in licensed or official photos for any public use.

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

## Phase 7 - Evaluation, monitoring, validation and LLMOps report (Evidently)

This phase is split into 7.0-7.7 below. The bullets directly under this heading are the base evaluation runner (7.1);
sections 7.0 and 7.2-7.7 add Evidently and are specified after them.

- `app/eval/metrics.py` (pure: fact match, citation hit, refusal detection, hit@k, disclaimer detection) + unit tests.
- `scripts/run_evaluation.py --modes direct,rag,rag_peft,rag_peft_base --set academic_synthetic [--workflow] [--mlflow] [--judge --max-judge-calls 40]`.
  Invokes the graph in-process; `rag_peft_base` uses `build_model3_client(settings, served_model=MODEL3_ABLATION_MODEL)`.
- Outputs `storage/eval/<run_id>/results.csv`, `summary.json`; workflow cases checked against expected intent/action.
- Calibrate `RAG_MAX_DISTANCE` from retrieval distances of answerable vs unanswerable questions.
- Fill `docs/MODEL_COMPARISON_TEMPLATE.md` from `summary.json` (no invented numbers).
- Optional `GET /api/admin/experiments/summary`.

---

### Evidently additions to Phase 7

Source: https://www.evidentlyai.com/ and https://github.com/evidentlyai/evidently (Apache-2.0). Docs read on 2026-11-24;
PyPI latest is **0.7.23** (Python >= 3.10). See `docs/DECISIONS.md` ADR-014 and `docs/TECHNICAL_REFERENCES.md`.

**Ground rules for every 7.x step**
- Evidently runs **offline only**: `app/` never imports it. Dependencies go in a new `backend/requirements-eval.txt`
  (`-r requirements.txt` + `evidently>=0.7.23,<0.8`) with its own lock; the app and its tests keep working without it.
- Use the **0.7 API** (`from evidently import Dataset, DataDefinition, Report`; `TextEvals`; per-metric `tests=[...]` with
  `eq/gte/lte`; `Report.run(current, reference)`). The old `ColumnMapping`/`TestSuite` style is gone; do not copy old tutorials.
- **Deterministic metrics first.** Pure, stdlib functions in `app/eval/metrics.py` (unit-tested) are wrapped as Evidently
  `CustomColumnDescriptor`s, so the code that is tested is the code that is reported.
- **LLM judges are optional and capped.** Off by default; `--judge --max-judge-calls N` samples rows; judge provider/model are
  settings (`EVAL_JUDGE_PROVIDER`, `EVAL_JUDGE_MODEL`, in `config.py` and `.env.example`), preferably *not* the answering model
  (a model grading itself is biased). Judge calls and cost are written to `summary.json`. Tests and CI never call a judge: they use a fake judge function.
- **No student text leaves the box.** Evaluation data is synthetic. Live traces keep message text off by default
  (invariant 7), so text-quality metrics come from evaluation runs; trace monitoring uses metadata unless `TRACE_INCLUDE_TEXT=true` is opted into for a dev session.
- Evidently reports are artefacts under `storage/eval/<run_id>/` and a local workspace under `storage/evidently/` (both git-ignored).

**7.0 Install spike - DONE 2026-11-24** (throwaway venv outside the repo; nothing was installed into `backend/.venv`)
- [x] `evidently==0.7.23` installs and runs the offline example (`TextLength`, `IncludesWords`, `CustomColumnDescriptor`, `TextEvals`,
      `.dict()`, `.save_html()`); import takes about 5 s; the HTML report is about 3.6 MB.
- [x] **Pin `pandas>=2.2,<3`.** Evidently 0.7.23 does not pin pandas; with pandas 3.1.1 `import evidently` fails (it imports a function pandas 3
      removed). Recorded in `backend/requirements-eval.txt`.
- [x] Windows Application Control: scipy, scikit-learn, statsmodels, nltk, plotly, litestar and `numpy.random` import fine. Of 297 compiled modules, 4 were
      blocked (`pyarrow._dataset`, two in `scipy.signal`, one in `statsmodels.tsa`); none are used by our flows, and a Parquet round-trip still works.
      Baselines are stored as JSONL/CSV anyway. Fallback if a future feature hits a block: run that part in CI (Linux).
- [x] The `[llm]` extra is not needed. `litellm>=1.74.3` resolves next to `openai==3.57.0` (resolver dry run only; a real judge call is not tested yet).
- [x] **CI pass/fail:** `snapshot.dict()["tests"]` is a list; each item has `status` (SUCCESS / FAIL), a `description` ("Actual value 18.667 < 20.000") and
      `test_config.is_critical`. The runner exits 1 if any critical test is not SUCCESS. `Report(..., include_tests=True).run(current, reference)` works.
- [x] **Slicing exists:** `GroupBy(metric, "column")` (`evidently.metrics`) runs a metric and its tests once per label of a categorical column. Verified: a
      "typos" slice failed a length threshold while "formal" passed. The gap is the difference between per-label values. A `BiasLLMEval` judge descriptor also exists.
- [x] Library synthetic-data API: no module found in 0.7.23 (file-name search); adversarial/synthetic generation is Cloud-only as documented, so we author our own sets.
- **Decision: go.** Next: 7.3 (adversarial suite) and 7.6 (workflow parity), neither needs RAG; then Phase 2.

**7.1 Evaluation runner** (the bullets above): `app/eval/metrics.py`, `scripts/run_evaluation.py`; builds an Evidently `Dataset`
from `results.csv` for the sections below.

**7.2 Prompt and response monitoring** (use-case 1)
- [ ] Row-level descriptors: `TextLength`/`WordCount`; refusal (exact refusal sentence); Model 1 disclaimer present; citation indices valid
      (`[n]` exists); PII regex (reuse `app/domain/redaction.py`); optional `ToxicityLLMEval` (judge); relevance via `ContextRelevance`/`SemanticSimilarity`
      (optional; `SemanticSimilarity` downloads a small embedding model, so decide first, see open questions); hallucination proxy = numbers/dates in the answer
      that are absent from the retrieved context, plus optional `FaithfulnessLLMEval`.
- [ ] `scripts/monitor_traces.py`: build a `Dataset` from `storage/traces/requests.jsonl` (latency, tokens, cost, intent, handled_by, grounded, error code,
      action status) and run a `Report` with tests (error rate, p95 latency, no-evidence rate, refusal rate); compare two windows with `run(current, reference)`.
- [ ] Self-hosted workspace (`evidently ui`, local only) with projects `helpdesk-eval` and `helpdesk-monitoring` to see trends across runs.
- Acceptance: a CI-safe report is produced from a fake-LLM run; a deliberately degraded fake run makes a test fail.

**7.3 Adversarial and edge-case testing** (use-case 2) - **core DONE 2026-11-24**
- [x] `data/eval/adversarial.jsonl`: 52 synthetic cases, 45 `structural` (run in CI with fakes) and 7 `model` (live LLM, heuristic, human review).
      Categories: prompt injection, jailbreak, transcript forgery, delimiter break, markup injection, prompt leak, secret exfiltration, identity bypass
      (garbage / tampered / expired / unknown-applicant tokens, identity claimed in chat, look-alike email), cross-applicant access, email redirection and
      flooding (CC/BCC, header injection, "use this address instead"), unsupported actions, filter evasion, injection strings (SQL, wildcard), edge inputs
      (empty, 2001 chars, unicode/RTL, control characters), model substitution, disclaimer removal, poisoned retrieved context.
- [x] `tests/integration/test_adversarial.py` runs every structural case through the real graph with fakes; the pure checks live in `app/eval/adversarial.py` and
      are unit-tested to FAIL on bad data (`tests/unit/test_eval_adversarial.py`). Global rule on every case: no configured secret may appear in a prompt or an answer.
- [x] Evidently: `scripts/evidently_report.py adversarial` -> HTML + JSON, exit code 1 on a critical breach (proved with an injected breach). Verified in the throwaway
      venv; install into `backend/.venv` happens in 7.1.
- [ ] Live variant for Models 1/2/3 (the 7 `model` cases, plus the structural ones against a real LLM; capped; humans review the heuristic checks): needs the 7.1 runner.
- [ ] Optional LLM-generated variants (capped, human-reviewed before committing).
- **Result:** 45/45 structural cases pass, 0 critical breaches. **Finding, fixed:** adv-048 showed retrieved text could forge the `<<<` / `>>>` context delimiters;
  `neutralise_delimiters()` now defuses them (prompt version `rag-v2`, shared by Models 2 and 3).
- Acceptance: every case has an expected result [x]; 0 critical breaches [x]; runs in CI [ ] (workflow in 7.5).
- Note: Evidently's own adversarial-data generator is **Cloud-only**, so the set is authored here.

**7.4 RAG evaluation** (use-case 3) - needs Phase 2
- [ ] Retrieval: hit@k, MRR, source recall (pure functions) on `academic_synthetic.jsonl`; optional `ContextRelevance(aggregation_method="hit")`
      and `ContextQualityLLMEval`.
- [ ] Generation vs context: deterministic fact match, citation hit, refusal correctness on u01-u05; optional `FaithfulnessLLMEval`, `CompletenessLLMEval`,
      `CorrectnessLLMEval` (judge, capped).
- [ ] Calibrate `RAG_MAX_DISTANCE` from distances of answerable vs unanswerable questions.
- [ ] Model 2 vs Model 3 vs `rag_peft_base` on identical retrieved context, so differences isolate the generator.
- Acceptance: a per-mode report and a filled `docs/MODEL_COMPARISON_TEMPLATE.md` (no invented numbers).

**7.5 Pre-deployment validation pipeline** (use-case 4)
- [ ] Baseline = the last accepted run per mode, stored small and synthetic in `data/eval/baselines/`; candidate = a new prompt version, model ID,
      adapter, or chunking setting. `Report([...tests...]).run(candidate, baseline)` with thresholds (`gte`, `lte`, `Reference(relative=...)`).
- [ ] Data-quality checks on the evaluation sets themselves (missing fields, duplicates, **no eval question in `data/peft/train.jsonl`**).
- [ ] The runner exits non-zero when a critical test fails (mechanism confirmed in 7.0; fallback: compute pass/fail in our code from the same thresholds).
- [ ] `.github/workflows/ci.yml`: ruff, pytest, `npm run build`, secret scan on every push/PR (the repo is public: no secrets in logs, no live LLM calls on forks).
      `.github/workflows/eval-gate.yml`: on PRs touching prompts, graph, llm, rag or eval data: fake-LLM deterministic eval + adversarial suite +
      Evidently tests, `report.html` uploaded as an artifact; an optional, manually triggered, capped live run using a repository secret.
- [ ] A PEFT adapter (Phase 6) is promoted only when these gates pass against the baseline; record the result in `adapter_manifest.json`.

**7.6 Bias and fairness audit** (use-case 5) - **phrasing and name parity DONE 2026-11-24; applicant-side and answer-quality slices pending**
- [x] Phrasing slices: 60 messages, 7 styles x 3 requests (formal, informal, typos, non-native, Hinglish, caps/punctuation, emoji) in `data/eval/parity_cases.jsonl`.
- [x] Name and programme parity: 10 names and 5 programmes never change the intent (unit tests); 8 names through the real graph give identical responses for
      resend / interview / status (`tests/integration/test_parity.py`).
- [x] Baseline and regression guard: `data/eval/baselines/parity_intent_baseline.json`. A slice may improve but not drop. `scripts/evidently_report.py parity` uses
      `GroupBy` per slice (warning below 90%) and exits 1 on a regression.
- **Finding, FIXED 2026-11-24 (ADR-015):** rules alone route typos and Hinglish at **0%** (caps 100%, formal 89%, emoji 83%, informal 78%, non-native 67%); best-vs-worst
  gap 1.00 against a target of <= 0.10. Fix: a gated, label-only LLM fallback. Live result (gpt-6-luna, run twice): **60/60 correct, gap 0.00**, 26 calls, about $0.0009,
  recorded in `data/eval/baselines/parity_intent_hybrid_live.json`. CI keeps guarding the rules-only baseline and uses a scripted classifier.
- [ ] Applicant-side slices (programme, interview mode, application status) for workflow correctness, and answer-quality slices (fact match, refusal rate) for
      Models 1/2/3: need the 7.1 runner and Phase 2.
- Limits stated in every report: tiny synthetic sample, so effect sizes and bootstrap intervals only, never claims of statistical fairness; this is an audit
  harness, not a certification.

**7.7 Reporting**
- [ ] `storage/eval/<run_id>/{results.csv,summary.json,evidently_*.html}`; optional MLflow run (existing); optional `GET /api/admin/experiments/summary`.

**Open questions for the team** (answers change the design)
1. Which model should act as judge for LLM-judged metrics (a different model from `gpt-6-luna` is recommended)?
2. Allow Hugging Face models that run locally (toxicity classifier, sentence embeddings; needs `torch`)? Default proposal: no; use rule-based + capped LLM judge.
3. Evidently Cloud (free tier) or self-hosted UI only? Default proposal: self-hosted only (nothing leaves the machine).
4. Should the adversarial suite and fairness checks be built before Phase 2 (recommended, since neither needs RAG)?

---

## Phase 8 - Hardening and packaging

- Per-IP rate limit on `/api/chat`; request size limits; CORS check.
- CI on GitHub Actions and the evaluation gate (specified in 7.5); branch protection on `main` once CI is green.
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
