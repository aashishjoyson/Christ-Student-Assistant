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
- **Update 2026-11-24:** the parity audit (Phase 7.6) showed the rules miss typos and Hinglish entirely; the LLM fallback
  announced here was added as ADR-015. The rules still run first and still handle everything they recognise.

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

## ADR-014 Evidently as the offline evaluation, monitoring and validation engine
- **Decision:** Use Evidently 0.7.x (Apache-2.0) for evaluation reports, monitoring of trace metadata, candidate-vs-baseline
  validation tests and per-slice fairness reports. It lives in `requirements-eval.txt`, runs from scripts and CI, and is **never
  imported by `app/`**. Deterministic metrics are pure functions in `app/eval/metrics.py`, wrapped as custom descriptors.
- **Why:** One tool covers the five required use-cases (response monitoring, adversarial testing, RAG evaluation, pre-deployment
  validation, bias audit) with HTML reports, tests with pass/fail conditions and a local UI, instead of hand-building each report.
- **Constraints / consequences:**
  - LLM-judged descriptors need an LLM provider (OpenAI by default through LiteLLM): optional, capped, off in tests and CI. Judge model is configurable and should differ from the answering model.
  - The `[llm]` extra pulls `torch`/`transformers`; not installed by default (no local LLM inference). Hugging Face descriptors (e.g. toxicity classifier) are a separate decision.
  - Evidently's adversarial-data generator and some no-code features are Cloud-only; the adversarial set and fairness slices are authored in this repo.
  - Install validated by the 7.0 spike (2026-11-24): works with `pandas<3`; four unused compiled modules are blocked by Windows Application Control on the dev machine; fallback for any blocked feature is CI (Linux). Pass/fail is read from `snapshot.dict()["tests"]`; per-slice reports use `GroupBy`.
  - The API changed substantially in 0.7 (`Dataset`/`DataDefinition`, tests inside `Report`); old tutorials do not apply. Pin the version.
- **Alternatives considered:** hand-rolled reports only (more code, no UI, no tests framework); MLflow only (already optional, weaker on LLM descriptors and pass/fail tests); Ragas/DeepEval-style libraries (not requested).

## ADR-015 Gated LLM fallback for intent labelling (typos, Hinglish, non-native phrasing)
- **Context:** The Phase 7.6 audit measured the deterministic rules at 0% for typo'd and Hinglish requests (best-vs-worst slice gap 1.00). Those
  students were sent to general Q&A and could not reach interview, status or email help. It failed safe but was unfair.
- **Decision:** In `classify_intent`, when the rules fell through to the default AND a loose gate sees a topic word (typos allowed) plus a
  first-person or Hinglish cue, make ONE small call to the primary hosted LLM that returns a single label from a fixed list. Anything unclear,
  empty, ambiguous or failing means `academic_qa`. Switch: `INTENT_LLM_FALLBACK` (default on). Pure helpers: `app/domain/intent_fallback.py`.
- **Safety:** the label only picks a route. Private intents still pass `verify_identity` (signed token), the eligibility policy and the recipient read
  from the database, so a wrong or manipulated label cannot leak data or redirect email (adversarial cases adv-049..054). The classifier sees only the
  current message (quoted, delimiters neutralised, truncated to 500 chars): no history, no applicant data, no tools, no SQL.
- **Measured (live, 2026-11-24, gpt-6-luna):** 60/60 phrasings routed correctly, gap 0.00 (was 1.00); 26 calls, 0 errors, about $0.0009 in total,
  about 1.3 s per call. Ordinary questions never open the gate (0 of 32 in the test set); one gate-open control ("mail ID of the admissions office") stayed academic.
- **Consequences:** Applicant and help answers are still templates, but those paths may now include one classification call, so PRD AC-02.2 says
  "no LLM-written answers" (not "zero LLM calls"). `usage.intent_llm_called` and the trace record the call and its cost, and the `handled_by` label
  says "an LLM only read the request" when it happened (labels must stay truthful). The call uses the primary model for every mode, so Models 1/2/3
  see the same front end. Costs one extra round trip only on gated messages. The CI suite uses a scripted classifier; the live result is a recorded
  baseline (`data/eval/baselines/parity_intent_hybrid_live.json`), refreshed by `scripts/eval_intent_fallback.py --save-baseline`.

## ADR-016 Follow-up questions are searched with their conversation context
- **Context:** The chat history reached the answering LLM, but retrieval embedded only the latest message. Live, "And what about the mid semester ones?" retrieved
  calendar pages and Model 2 answered "could not find"; a third follow-up got a canned refusal.
- **Decision:** In `retrieve_context`, when the conversation has an earlier user turn AND the new message looks like a follow-up (<= 15 words, or it leans on earlier text:
  "that", "same", "what about"...), the primary LLM restates it as ONE standalone question (`app/domain/contextualize.py`). That text is used for retrieval ONLY: the
  answering model still gets the original message plus the history. Any failure falls back to "previous question + this message".
- **Safety and fairness:** the rewrite prompt is quoted data with delimiters neutralised, sees at most the last 6 turns (clipped), and applicant-service answers are only
  the history placeholder, so applicant details never reach it. Models 2 and 3 share the step (same primary client), so they keep identical retrieval (ADR-003).
- **Consequences:** one extra small call (about $0.0001, about 1 s) on follow-ups only; `usage.condense_llm_called`, trace fields and tests record it; the trace stores
  only whether the query was rewritten (`llm` or `fallback`), never its text.

## ADR-017 Streaming answers over Server-Sent Events, rendered as safe markdown
- **Decision:** Add `POST /api/chat/stream` (SSE: start, delta, final, error). `OpenAICompatibleChatClient.stream()` yields text deltas then one `ChatResult`; the answer nodes
  emit them through LangGraph's custom stream writer only when the turn was started with `stream=true`, so `POST /api/chat` is unchanged. The UI renders answers with an
  in-repo markdown parser that builds React elements (no `dangerouslySetInnerHTML`, only http/https/mailto links, unclosed markers stay literal).
- **Why:** reasoning models make the user wait seconds for the first word; streaming shows progress at once, and models write markdown that was displayed as raw `**` and dashes.
- **Consequences:** a failure before the first word is a normal HTTP error (the 503 for an unconfigured Model 3 is preserved); a failure after text starts ends with an
  `error` event. The first word still waits for hidden reasoning: lower `LLM_REASONING_EFFORT` to shorten it. Frontend logic is covered by dependency-free `node --test`
  tests (`npm test`) until Vitest arrives in Phase 4. Streaming needs `stream_options.include_usage` support from the provider (OpenAI, OpenRouter and vLLM have it).

## ADR-018 Automatic ingestion by polling a source-agnostic engine; Drive is read-only and non-recursive
- **Context:** the user wants a new document dropped into a Drive folder to become answerable without running a command. Drive push notifications need a public HTTPS
  endpoint, which a local prototype does not have.
- **Decision:** an asyncio `IngestionPoller` (started in the FastAPI lifespan when `DRIVE_POLL_ENABLED=true`) calls `IngestionService.sync("poll")` in a worker thread every
  `DRIVE_SYNC_INTERVAL_SECONDS`. It does not know about Drive; any `DocumentSource` works. One lock is shared by all sources, so a manual sync, the poller and a second
  source never write at the same time (a busy poll is `skipped_busy`, not a failure). Failures back off to `interval x 2^n` (cap one hour) and count toward the admin status.
  `GoogleDriveSource` lists one folder (non-recursive; sub-folders and shortcuts are reported, not followed), uses md5 for binary files and `version` + `modifiedTime` for Google
  Docs/Sheets (which have no md5), exports Docs to DOCX and Sheets to XLSX, and lets the file extension win over Drive's generic labels (`text/plain` for `.md`).
  Every chunk carries "Document: <file name>" so questions that name a document find it.
- **Why:** polling is the only trigger that works from a laptop; a shared lock and "new version before deleting the old one" mean a failure at any step leaves the last good index
  answering. Drive access is `drive.readonly`, and a listing failure never deletes anything (an outage must not look like "every file was removed").
- **Consequences:** a change shows up within one interval (default 5 minutes), not instantly. Switching the source of truth needs `--purge-local` once so the same document is not
  indexed twice. Push (`changes.watch`) can replace the trigger later without touching the engine.

## ADR-019 A golden question set with proven facts, and a frozen-configuration evaluation run
- **Decision:** `data/eval/academic_real.jsonl` holds questions with the facts a correct answer must state. Every answerable case carries `evidence`: literal quotes from the real
  documents, and every unanswerable case carries `absent_terms` that occur in no document. `scripts/check_golden_set.py` proves both against the documents, so no expected fact is invented
  (it caught four of my own "absent" terms that were in fact present). `scripts/run_evaluation.py` asks every question in every mode through the real graph and writes a run folder whose
  `config.json` freezes everything that can change an answer (git commit, prompt versions, model ids, retrieval settings, golden-set hash, fingerprint of the indexed files).
- **Why:** an answer cannot be called better or worse without a fixed question set and a known configuration. Deterministic matching (normalised text, accepted wordings joined by `|`) keeps the
  check cheap, repeatable and free of a second model's bias; its blind spots are written down in the report (a correct fact with a wrong extra claim still passes).
- **Diagnostics that decide what to fix:** `context_recall` (the proving quote reached the model) separates retrieval failures from generation failures; `routed_academic` shows questions sent to the
  personal-data path; the distance calibration shows whether a cut-off can separate answerable from unanswerable questions at all (on this data the two groups overlap, so the LLM's own refusal does that job).
- **Consequences:** a run costs about half a cent and about two minutes. Identical settings move by about one question between runs, so differences of one question are noise. Settings tuned on
  this set are optimistic for unseen questions; a held-out set is a listed follow-up. The run keeps its own trace log so evaluation never mixes with real traffic.

## ADR-020 Structure-aware parsing and lexical re-ranking, adopted because the evaluation measured them
- **Decision:** (1) Calendar pages are split per dated entry and every entry repeats `Month: <month year>` (a calendar page is recognised by at least five dated lines; the month never carries over a non-calendar page).
  (2) A markdown block with three or more one-line questions becomes one section per question and answer. (3) HTML and pasted CSS are removed from spreadsheet cells. (4) Retrieval fetches a wide candidate pool
  (150) by meaning and keeps the best 8 after rewarding passages that contain the query's rare words (`app/rag/rerank.py`); the reported cosine distance is unchanged. (5) The two intent-routing errors the
  evaluation found are fixed (a Roman numeral "I" in "Session-I" was read as the student; the classifier prompt, now `intent-llm-v2`, says an "unsupported" request must ask us to change something).
  (6) `sync --force` re-parses everything and re-embeds only chunks whose text changed, so a parser change reaches the index without paying for unchanged files.
- **Evidence (same 38 questions):** 70% first run; 83% after parsing and routing fixes alone; 93% with top-k 8, cut-off 0.75 and the re-rank. Context recall 90% -> 100%, MRR 0.90 -> 0.94.
  A re-rank over a pool of 40 showed no gain because the right passage was not in the pool; a pool of 150 did.
- **Consequences:** the calendar chunks are small (one entry each), so a question that needs a whole month ("list the November holidays") depends on top-k. `.env` files that pin `RAG_TOP_K` or `RAG_MAX_DISTANCE`
  override the new defaults. The two remaining misses are spreadsheet fee questions where many near-identical programme rows compete.

