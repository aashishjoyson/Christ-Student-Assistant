# Evaluation prep guide: what to explain, and how

Read sections 1 to 3 first (10 minutes). Sections 4 to 8 are for looking things up. Section 9 (hard questions) is worth reading twice.
Every number here comes from a recorded run (`BUILD_REPORT.md`, `docs/MODEL_COMPARISON_REPORT.md`); where something was **not** measured, it says so. If an evaluator
pushes on something, the honest answer is always in section 8 or 9: this project's strength is that it measures itself and reports what it finds.

---

## 1. The pitch (say this first, 60 seconds)

> "This is a student helpdesk for a university website. A visitor can ask questions about the calendar, handbook, courses and FAQ, and an applicant can look up their own
> interview and ask for the interview email again. The point of the project is not the chat box; it is **everything around it that makes an AI system trustworthy
> to run**: answers come from the university's own documents and carry citations; those documents are kept current automatically from Google Drive; every change to a
> prompt, model or setting is measured against a fixed 38-question set and has to pass a regression gate; the system watches itself while it runs; and I compared three ways
> of answering: a plain LLM, an LLM with retrieval, and a fine-tuned open model on its own GPU endpoint. The honest result is that retrieval is what matters: 10% without
> documents, 93% with them, and my fine-tuned model did not beat its own base model. I report it that way."

If you only have 3 minutes, add: *"Here is a live dashboard that shows, as I type, which service is hit, in what order, how long each took, and what Evidently says about the last evaluation."*

## 2. The story in five beats (for any length of talk)

1. **Problem:** a plain LLM does not know this university. Measured: 3 of 30 questions right (10%). It must not be trusted for facts.
2. **Grounding (RAG):** answer only from the university's own documents, with numbered citations, and say "I could not find this" otherwise. Measured: 28 of 30 (93.3%).
3. **Keep it current:** the documents live in a Google Drive folder; a poller notices edits and deletions and re-indexes only what changed. Nothing about the university is written in code.
4. **Measure and gate (the LLMOps core):** golden set proven by literal quotes, frozen run configuration, Evidently reports, tolerances taken from measured noise, a promotion rule, CI on every push, monitoring with alerts and thumbs feedback.
5. **Compare and be honest:** Model 3 (Qwen3-4B + LoRA on a Modal GPU) scored 24 of 30; the same base model without the adapter scored 28. The adapter changed the answer *style* (shorter, one citation) but not accuracy. It is not promoted, and I did not tune it afterwards (ADR-025).

## 3. What to show, in order (about 15 minutes)

| Step | Show | Say |
|---|---|---|
| 1 | Open the chat, switch Model 1 / 2 / 3 | "Three honest labels: no documents, documents, documents plus a fine-tuned model." |
| 2 | Model 2: *What attendance do I need to sit the mid semester examination?* | Streams, cites the handbook page with a link to Drive. "75% per course." |
| 3 | Same question on Model 1 | It opens with "I have not checked official university documents, so this may be inaccurate." This is the 10% result in one screen. |
| 4 | Open **#/flow** next to the chat, ask again | The map lights up in order: browser, API, rules, graph, embeddings, Chroma, re-rank, hosted LLM, trace. The timeline shows each step's milliseconds and a plain sentence. |
| 5 | Applicant: verify as `CUAPP-DEMO-0001` with your own address, then *I have not received my interview email* | The email flow tab shows verify, rules, reserve, SMTP connect / TLS / login / send, audit. **A real email arrives in the inbox.** The recipient came from the database, never from the chat. |
| 6 | Ask it again | Refused by the cooldown (15 minutes, 3 per day). Idempotent. |
| 7 | **#/flow** tab "Evidently" | "Evidently turns each evaluation run into a report; one critical test (no invalid citation) passes." Show the bars per model. |
| 8 | `python scripts/compare_eval.py latest` | "The gate compares a run with the accepted baseline; a critical regression would fail it." |
| 9 | `docs/MODEL_COMPARISON_REPORT.md`, section 6 | "Model 3 did not beat its base. I report it, I did not tune it." |
| 10 | Admin page `#/admin` | Documents indexed, evaluation table, monitoring, alerts, thumbs. |

The full script with commands is `docs/DEMO_SCRIPT.md`.

---

## 4. The architecture in plain words

**Request path (what happens when someone types a message)**

1. The React widget sends `POST /api/chat/stream` with the message, the chosen model and (for applicants) a signed session token.
2. FastAPI applies a per-client rate limit and runs one **LangGraph** turn: a graph of 15 small nodes over one shared state, with plain-Python routing between them.
3. `classify_intent` uses **deterministic rules** first (free, instant). Only if the rules fall through to the default *and* the message looks like a personal request is one small LLM call made, and it may only return **one label** from a fixed list.
4. **Academic questions** (Models 1/2/3): Model 1 calls the hosted LLM with no documents. Models 2 and 3 first `retrieve_context`: embed the question (OpenAI `text-embedding-3-small`), search Chroma for 150 candidates by meaning, **re-rank** by the question's rare words, keep the best 8 under a distance cut-off; a follow-up is first rewritten into a standalone question (for searching only). If nothing passes, a fixed "I could not find this" answer is returned **without calling the model**. Otherwise the model answers from numbered passages and must cite `[n]`. Model 3 is the same prompt and the same passages, answered by a LoRA-adapted Qwen model on Modal.
5. **Applicant questions** never reach a model for facts: `verify_identity` checks a signed token, fixed repository queries read the applicant's own record, and a template writes the answer.
6. **The interview email**: `check_resend_eligibility` applies the rules (active future interview, 15-minute cooldown, 3 per day, recipient allowlisted) and **reserves** the send with a UNIQUE key; `send_interview_email` re-reads the recipient from the database and sends through SMTP; `record_notification` writes the outcome. `sent` is recorded only after the server accepted the message.
7. The turn ends with one **text-free trace line** (model, tokens, cost, retrieval distance, path) and the answer streams back as Server-Sent Events.

**Data path (what keeps the answers current)**: Google Drive folder → poller (every 300 s; 60 s for the demo) → ingestion (checksum check, download only changed files, parse with structure-aware parsers, chunk 900/120, embed, upsert; the old version is removed only after the new one is in) → Chroma. Edits and deletions are detected; unchanged files cost nothing.

**LLMOps loop**: golden set → `run_evaluation.py` (frozen config: commit, prompt versions, model ids, retrieval settings, index fingerprint) → metrics + Evidently report → `compare_eval.py` against the accepted baseline (tolerances from measured noise) → promote (with a written reason) or stop → CI on every push → monitoring of live traces (latency, cost, refusals, distance drift, alerts) and thumbs feedback → next change.

The two diagrams in the deck show exactly this: *End-to-end architecture* and *LLMOps architecture*.

---

## 5. Feature by feature

Each block: **what / why / how (talk track) / honest limit.**

### 5.1 Three model paths
- **What:** Model 1 = hosted LLM alone. Model 2 = same LLM + retrieved passages. Model 3 = retrieval + a LoRA-fine-tuned open model on a Modal GPU.
- **Why:** to *measure* what each ingredient is worth. Models 1 and 2 use the same model id, so the difference is retrieval alone. Models 2 and 3 use the same passages and prompt, so the difference is the generator.
- **Invariants (tests exist):** Model 1 never calls the retriever; Model 3 never falls back to another model (not configured → 503; endpoint error → 5xx); no model output is ever labelled as another model's.
- **Limit:** Model 2 and 3 differ in size and provider; the clean comparison for the adapter is Model 3 vs the base model without it.

### 5.2 Retrieval-augmented generation
- **How:** parse (PDF, XLSX, Docs, Markdown) with structure-aware parsers; chunk to 900 characters with 120 overlap; embed with `text-embedding-3-small`; store in Chroma 1.5.9; query 150 candidates, lexical re-rank (weight 0.30), keep top 8 under a distance of 0.75.
- **What the evaluation taught us (say this, it shows engineering):** 70% → 83% → 87–90% → 93%. The first step was *parsing*: calendar entries had lost their month, FAQ answers were cut across chunks, 25 spreadsheet rows contained pasted CSS, and a Roman numeral "I" was read as the student. Then the distance cut-off (0.6 rejected true answers) and the re-ranker.
- **Limit:** settings were tuned on the same 38 questions, so 93% is optimistic for unseen questions. A held-out set is the next step. The weakest area is the fee spreadsheet (1 of 3): many near-identical programmes at different campuses.

### 5.3 Intent routing (rules first, LLM only for a label)
- **Why:** cheap, predictable, testable. A model decides only when the rules are unsure, and it can only pick a label; it never sees applicant data and never writes SQL.
- **Evidence:** phrasing parity audit: 60 messages in 7 styles (formal, informal, typos, non-native English, Hinglish, caps, emoji): with the label fallback every slice routed 100% correctly in one live run; rules alone scored 0% on typos and Hinglish. **Single live run of a non-deterministic model: not a guarantee.**

### 5.4 Follow-up questions
- *"And for the end semester examination?"* is rewritten into a standalone question **for retrieval only**. The model still sees the real conversation. ADR-016.

### 5.5 Streaming
- Server-Sent Events: `start`, `delta` (word by word), `final` (the canonical answer with citations). A failure before any text becomes a normal HTTP error; after text it ends the stream with an `error` event.

### 5.6 Google Drive ingestion
- **What:** the Drive folder is the source of truth. A service account lists the folder; Docs/Sheets are exported; files are skipped by checksum.
- **Why it matters (LLMOps = data pipelines):** freshness without a human running a command; lineage (every chunk carries its source file, page and version); safe updates (old version removed after the new one is in; one bad file never stops the sync).
- **Demo:** drag the four demo circulars in; ask; edit one (Replace existing file); ask again; trash one; it stops answering.
- **Limit:** a poll interval, not a push notification; Drive webhooks would need a public URL.

### 5.7 Applicant services and privacy
- Verification = application id + registered email → an HMAC-signed session token (30 minutes). **Demo-level, not production authentication** (a real deployment needs the university's single sign-on).
- The model never sees applicant data: answers are templates; the conversation memory stores only a placeholder for them; traces contain no message text.
- All applicant data is **synthetic** and labelled so.

### 5.8 The interview email (real sending)
- **What:** resend the interview details to the registered address, once per cooldown window.
- **Safety, each pinned by a test:** recipient read from the database inside the send function (text in the chat cannot change it, ADR in invariants); allowlist checked *before* anything is reserved; reserve-then-send with a UNIQUE key (two concurrent requests cannot both send); `sent` only after the server accepted; failure is audited and frees the window; TLS always on with certificate checks and **no downgrade** to plain text; one plain recipient address and no line breaks in headers (no Bcc injection); one attempt with a timeout; errors scrubbed of the password and addresses; the app refuses to start if real sending is half-configured.
- **Words to use:** "sent" means *the mail server accepted it*, not "delivered"; the chat says "please also check your spam folder".
- **Limit:** the verification step is demo-level; only the allowlisted address can receive mail; 61 tests use a pretend mail server, and the first real send was done by hand with `scripts/send_test_email.py`.

### 5.9 Evaluation harness and golden set
- **Golden set:** 38 questions on the four real documents: 30 answerable, **each proven by a literal quote** from the document; 8 unanswerable, **proven absent**. `scripts/check_golden_set.py` re-proves it. No expected fact is invented.
- **Run:** `scripts/run_evaluation.py` freezes the configuration (git commit and dirty flag, prompt versions, model ids, retrieval settings, index fingerprint) into the run folder, then scores every answer **deterministically** (facts present, refusal correct, citation valid). Metrics: accuracy, false/correct refusal, unsupported answers, citation hit and validity, hit@k, MRR, context recall, routing, latency, cost.
- **Why deterministic:** cheap, repeatable, no judge model to doubt. **Blind spots (say them):** a correct answer worded in an unlisted way counts as wrong; a correct fact with a wrong extra claim counts as right; a month-less date can pass (g09). An optional capped LLM judge is planned, not built.
- **Noise:** identical settings moved by about one question (2.6 points). One question is not evidence.

### 5.10 Evidently (what it does here)
- **Role:** Evidently turns each evaluation run's results into a **report and tests**. It does **not** judge answers (the deterministic checker already scored them). It summarises outcomes per model and per category (`correct`, `correct_refusal`, `false_refusal`, `wrong_answer`, `unsupported_answer`, `error`) and enforces **one critical test: no citation may point at a passage that was not supplied** (it passes: 0 invalid).
- **Other Evidently reports in the project:** the adversarial suite, the phrasing/fairness parity slices, and a data-drift report on live traces (`monitor_traces.py --evidently`).
- **Where it lives:** only in `scripts/` (needs `requirements-eval.txt`), never imported by the API. The dashboard reads the JSON it saved. The full HTML report is a few MB.
- **How to explain the split:** *Evidently = the picture and the tests for one run. `compare.py` = the decision across runs (baseline, tolerances, promotion).*

### 5.11 Promotion gate and CI
- **Rule:** a change is promoted only when a fresh run on the same golden set shows no critical regression against the baseline, and the reason is written down.
- **Gates (critical):** accuracy may drop at most 0.06 (two questions); correct refusals must not drop; unsupported answers must not rise; citation numbers must stay valid; routing may drop 0.03; no new errors. Warnings: context recall, citation hit, MRR, false refusals, p95 latency and cost (×1.5).
- **Why these tolerances:** taken from the measured noise, so noise does not fail a run and a real regression does.
- **Demo:** break it on purpose (`RAG_TOP_K=1`, no re-rank) → the gate FAILS and refuses promotion.
- **CI:** every push runs lint, 708 backend tests (including a 51-case adversarial suite), the frontend build and a secret scan, on Linux, with no key and no network. A manual `eval-gate` workflow exists for a live run; **it has not been run yet**.

### 5.12 Monitoring, feedback and the admin page
- Text-free traces, windowed summaries (traffic, errors, p50/p95, first-word time, cost per request, no-evidence rate, nearest-passage distance), **alerts with minimum sample sizes**, drift against the previous week, thumbs up/down with fixed reason codes, retention (traces 90 days, ratings 365, chats 30), per-client rate limits.

### 5.13 Model 3: fine-tuning (PEFT) and serving
- **What was taught:** *behaviour, not facts*: cite `[n]`, answer only from the passages, use the exact refusal sentence. Facts stay in retrieval so they can change without retraining.
- **Data:** 371 examples built from the real documents with the hosted model as a teacher (284 answerable, 87 refusals; train 344 / validation 27); every number in an answer is checked against the cited passage; **461 passages that prove a golden answer were held out** so the evaluation is fair.
- **Training:** QLoRA on a free Colab T4: 4-bit NF4, LoRA r=16, alpha 32, dropout 0.05 on all seven projection layers, 2 epochs, learning rate 2e-4, answers-only loss; 44 steps in 32 minutes; validation loss 0.237 → 0.224. Libraries pinned (TRL 1.18.2, PEFT 0.22.0, Transformers 5.24.0).
- **Registry:** a private Hugging Face repository; an **adapter manifest** ties the adapter to the dataset hash, the prompt version and the base model commit. A script refuses to call an endpoint "Model 3" unless it lists the adapter as a LoRA of the configured base.
- **Serving:** vLLM 0.34.0 on Modal with `--enable-lora`, behind an OpenAI-compatible API (so the backend needed no new code), API key required, adapter fetched at an exact commit.
- **Result (say it plainly):** 24/30 vs 28/30 for the same base without the adapter. Style changed, accuracy did not improve. Not promoted. Not tuned afterwards (ADR-025).

### 5.14 The live flow dashboard (`#/flow`)
- **What:** an admin-only page: the real chat on the left, a live map and timeline on the right. Every graph node, the retriever's embed/search/re-rank, the email steps and ingestion publish events (which component, what, how long) to an in-memory log that the page reads as a stream.
- **Privacy:** events carry **no message text, answers, passages or unmasked addresses** (tests prove it on real chat turns). Memory only; gone on restart; admin key required.
- **Tabs:** *Live request* (map + step timeline), *LLMOps pipeline* (data and evaluation loop with live status), *Email* (the steps of a send), *Evidently* (role, tests, outcomes per model).

---

## 6. Tech stack: what and why

| Piece | Used for | Why this one | Considered / trade-off |
|---|---|---|---|
| **React + Vite + TypeScript** | the chat widget, admin page and flow dashboard | small, fast dev loop, typed API client | no UI library: less code to explain; no router library (two hash routes) |
| **FastAPI + Pydantic** | the API and schemas | typed, async-friendly, automatic validation, SSE streaming | Flask would need more glue |
| **LangGraph** | the workflow (15 nodes, shared state, checkpointer) | explicit, testable control flow: routing is plain Python, each node is a small function | a hand-written `if` chain is simpler but gives no per-node path/timing or checkpointing |
| **OpenAI hosted model (`gpt-6-luna`)** | Models 1 and 2, intent label, follow-up rewrite | strong, cheap per call; one client for all three paths | cost and provider dependence; mitigated by pricing table and traces |
| **OpenAI `text-embedding-3-small`** | embeddings | good quality per cost | local embeddings would add local inference (ruled out by design) |
| **Chroma** | vector store | local, persistent, simple, no server | a hosted vector DB scales further; unnecessary for ~2k chunks |
| **Lexical re-rank** | fix near-miss retrieval | measured +MRR and +accuracy; no model call | a cross-encoder would cost latency and a dependency |
| **SQLite + SQLAlchemy 2.0** | applicants, audit, feedback, indexing history | zero setup, typed models, UTC-aware datetimes | Postgres for production |
| **Google Drive API (service account)** | document source | the university's staff already use Drive; change signals (md5/version) | webhooks need a public URL |
| **Evidently** | evaluation reports and tests | open-source ML/LLM evaluation reports with tests; HTML for people, JSON for tools | used only in scripts so the API stays light |
| **GitHub Actions** | CI | free, runs with no key and no network | live gate is manual by design (cost, secrets) |
| **QLoRA (PEFT + TRL + bitsandbytes) on Colab T4** | train the adapter | free GPU; 4-bit lets a 4B model train in 16 GB | small data (344) → small effect; a bigger set or run is future work |
| **Qwen3-4B-Instruct-2507** | Model 3's base | Apache-2.0, ungated, non-thinking instruct variant, supported by vLLM and PEFT | larger models need larger GPUs |
| **Hugging Face (private repo)** | adapter registry | versioned by commit; never in Git | |
| **vLLM** | serve base + adapter | OpenAI-compatible API, native LoRA serving | HF Inference Endpoints is another option |
| **Modal** | the GPU host | per-second billing, **scale-to-zero**, a Python file is the whole deployment, monthly credit; a 4B model needs a GPU only while someone asks | a 24/7 GPU would cost far more for a demo; **cold start returns 503** for minutes, so it is warmed before a demo and the app never falls back to another model |
| **SMTP (Gmail app password)** | the real interview email | universal, no vendor SDK, `smtplib` in the standard library | a transactional email API (SES, SendGrid) is the production answer |
| **Docker / nginx files** | deployment | written and documented | **not built here** (no engine was running): say so |

---

## 7. Procedures (what you do, step by step)

**Index the documents:** put files in the Drive folder → the poller runs (or admin page → "Sync Drive now") → files show `indexed` with chunk counts. After changing the parser: `python scripts/sync_drive_once.py --force`.

**Measure a change:** `python scripts/run_evaluation.py --modes direct,rag --evidently` (about 2 minutes, under a cent) → `python scripts/compare_eval.py latest` (exit 0 = no critical regression) → `... --promote --reason "what changed and why"` → commit the baseline file.

**Compare Model 3 and its base:** warm the endpoint (`python scripts/check_model3_endpoint.py --wait 900 --ask --manifest data/peft/adapter_manifest.json`), then `python scripts/run_evaluation.py --modes rag,rag_peft,rag_peft_base --evidently`. Apply **rule 7**: the adapter must beat its own base. It did not, so it is not promoted.

**Train an adapter:** build the dataset (`scripts/build_peft_dataset.py`, about $0.03) → open `notebooks/train_lora_colab.ipynb` on a T4 → upload the three files in `data/peft/` → run → download the manifest into `data/peft/adapter_manifest.json` → validate it against the dataset hash.

**Deploy Model 3:** `python -m modal secret create cu-helpdesk-vllm HF_TOKEN=... VLLM_API_KEY=...` → `python -m modal deploy deploy/modal_vllm.py` → put the URL (+`/v1`) and key in `.env` → run the endpoint check. (`python -m` is used because the machine's Application Control blocks launcher executables.)

**Real email:** Gmail app password → `.env` (see `docs/SETUP_EMAIL.md`) → `python scripts/set_demo_email.py` → `python scripts/send_test_email.py --to <you>` → restart the API.

**Watch it run:** `#/admin` (monitoring, documents, evaluations), `#/flow` (live), `python scripts/monitor_traces.py` (text report with drift and alerts).

---

## 8. The numbers (all measured; one run each unless stated)

| What | Value |
|---|---|
| Golden set | 38 questions: 30 answerable (each proven by a quote), 8 unanswerable (proven absent) |
| Model 1 (no documents) | 3 / 30 = **10%** |
| Model 2 (RAG) | 28 / 30 = **93.3%** (accepted baseline run: 27 / 30 = 90%; noise about 1 question) |
| Model 3 (RAG + LoRA) | 24 / 30 = **80.0%** |
| Base model without adapter (ablation) | 28 / 30 = 93.3% |
| Refusals of unanswerable questions | 8 / 8 for Models 2, 3 and the ablation; 0 invented answers |
| Citation hit | Model 2 93.3% · Model 3 73.3% · ablation 90.0% |
| Retrieval | hit@8 = 100%, MRR = 0.944, the proving quote reached the model 100% of the time |
| Latency p50 / p95 | Model 2 1.44 s / 2.14 s · Model 3 1.56 s / 2.64 s · ablation 1.50 s / 3.29 s |
| Cost per question | Model 2 about $0.00014; Model 3 is GPU time (an L4 was listed at about $0.80 per hour) |
| Answer length | Model 2 15 words · Model 3 14 · base model 29; citations per answer 1.25 · 1.00 · 2.43 |
| Index | 4 real documents, 2,253 chunks |
| Training | 371 examples (344 / 27), 44 steps, 32 min on a T4, validation loss 0.237 → 0.224 |
| Tests | 708 backend tests, 51-case adversarial suite (0 critical breaches), CI green |
| Decisions recorded | 27 ADRs in `docs/DECISIONS.md` |

---

## 9. Hard questions and honest answers

1. **"Is 93% reliable?"** It is measured on 38 questions and the settings were tuned on the same set, so treat it as strong evidence that the system works, not a precise accuracy. One question is 2.6 points. A held-out set is the next step.
2. **"Why not use an LLM as the judge?"** The deterministic check is cheap and repeatable and has written blind spots; a capped judge is planned, not built. I would rather have a check I can fully explain.
3. **"Your fine-tuned model is worse. Why keep it?"** Because the comparison is the result. The ablation shows the adapter changed style, not accuracy. Not promoted; not tuned afterwards, because the golden set had already tuned retrieval and tuning again would make the number meaningless.
4. **"Could you improve it?"** Probably: more and more varied training data, a held-out validation set, repeated runs to measure Model 3's own noise (it samples at temperature 0.2 and was run once). That is future work, deliberately not done to this result.
5. **"What did Evidently add that a script could not?"** A standard, inspectable report and a test runner, per model and per category. The *decision* is made by our gate against a baseline; Evidently is the evidence for one run.
6. **"Why LangGraph?"** Explicit nodes, shared typed state, per-node path and timing for traces and the dashboard, a checkpointer for conversation memory, and routing that is plain, testable Python.
7. **"Why Modal for Model 3?"** A 4B model needs a GPU only when someone asks. Modal bills per second and scales to zero, so a demo costs cents; a rented 24/7 GPU would not. The cost is cold starts: the endpoint returns 503 for minutes, so it is warmed before a demo and the app never substitutes another model.
8. **"Why is the model not allowed to write SQL / send email directly?"** Because a model can be tricked. The recipient and every email field come from the database inside the send function; the model only ever picks a label.
9. **"What stops prompt injection?"** Passages and messages are treated as data with delimiters that cannot be forged; the model has no tools; the dangerous actions are deterministic code behind rules. A 51-case adversarial suite runs on every push (0 critical breaches). It is not a proof; 7 live cases need a model and have not been run.
10. **"Is the applicant login secure?"** No: it is demo-level (application id + registered email). A real deployment needs single sign-on. The email can only go to the registered address and only if it is on the allowlist, whatever the chat says.
11. **"Did you send real email?"** Yes: through SMTP with TLS to the demo inbox; `sent` means the server accepted it. 61 tests use a pretend server; the first real send was done by hand.
12. **"What happens if the Drive is down or a file is bad?"** One bad file never stops the sync or loses the old version; the poller backs off; the admin page and an alert show a stale index.
13. **"How do you know the retrieval is good?"** Retrieval metrics on the golden set: hit@8 100%, MRR 0.944, and the proving quote reaches the model every time, so every failure is a generation problem, not retrieval.
14. **"What would you do with more time?"** Held-out question set; repeated runs; optional capped judge; a cross-encoder re-ranker; fee questions via a structured lookup; real sign-in; build and test the containers; run the live eval workflow.
15. **"What did you not test?"** The Docker build (no engine was running), the live `eval-gate` workflow, Model 3 through every browser path, and real delivery to many inbox providers.
16. **"Why does Model 1 exist if it is bad?"** It is the control. Without it, "RAG helps" would be a claim; with it, it is 10% vs 93%.
17. **"Why not train on the golden-set passages?"** That would pass the evaluation without learning anything. Those 461 passages were held out of training entirely.
18. **"How is cost controlled?"** Per-request cost in every trace, an alert on cost jumps, a gate warning at ×1.5, a rate limit per client, scale-to-zero on the GPU and a spend limit on the Modal account.
19. **"Is any data private?"** Applicant data is synthetic and labelled. Traces and live events contain no message text. Conversation memory is opt-in with retention and a delete endpoint.
20. **"How would you roll back a bad change?"** Revert the commit and, if a baseline was promoted with it, the baseline file; prompt versions and model ids are in every trace, so a rolled-back answer path is identifiable.

---

## 10. If something goes wrong during the demo

| Symptom | Cause | Do this |
|---|---|---|
| Model 3 answers with an error | the Modal endpoint is cold (503) | `python scripts/check_model3_endpoint.py --wait 900`; meanwhile show Models 1 and 2. Say: "it never borrows another model's answer". |
| "Could not find this" for a question that should work | the index is empty or the Drive sync has not run | admin page → Documents → "Sync Drive now" |
| An answer takes 7 s | the model provider was slow that hour | say so; it was 1.4 s median in the measured run |
| The email does not arrive | spam folder, or the allowlist, or the cooldown | check spam; the chat says why (`recipient_not_allowlisted` / `cooldown_active`); the flow tab shows where it stopped |
| `#/flow` is empty | wrong admin key, or the API restarted (events are in memory) | type `ADMIN_API_KEY` again and send one message |
| The API will not start after a `.env` change | a safety guard (real email half-configured) | the message names the missing setting; or set `EMAIL_PROVIDER=console` |

## 11. The day before (checklist)

- [ ] `.env`: `RAG_TOP_K=8`, `RAG_MAX_DISTANCE=0.75`, `ADMIN_API_KEY` set, `DRIVE_SYNC_INTERVAL_SECONDS=60` for the demo (300 normally).
- [ ] Drive folder holds only the 4 real documents; the demo circulars are in `data/demo_docs/` ready to drag in.
- [ ] `python scripts/send_test_email.py --to <you>` → ACCEPTED, and the message is in the inbox.
- [ ] `python scripts/check_model3_endpoint.py --wait 900 --ask --manifest data/peft/adapter_manifest.json` → OK (10 minutes before).
- [ ] One question asked on each model; `#/flow` shows the events.
- [ ] A fresh evaluation exists in `storage/eval/` (`python scripts/run_evaluation.py --modes direct,rag --evidently`).
- [ ] The deck and the two diagrams open; you can say the five beats (section 2) without notes.
- [ ] After the demo: trash the demo circulars, set the poll interval back to 300, and stop or leave the Modal app (it stops itself 5 minutes after the last request).
