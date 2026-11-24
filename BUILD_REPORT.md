# Build report

## Streaming, formatted answers, follow-up context and the widget UI (2026-11-24)

| Check | Result |
|---|---|
| `pytest` (full backend) | **300 passed** (28 new: streaming, follow-ups, rewrite helpers, stream client); `ruff` clean; secret scan passed |
| `npm run build` / `npm test` | build passed; **13** dependency-free tests (markdown parser, SSE framing, HTML/`javascript:` safety) |
| Real browser (headless Edge driving the live UI, DevTools protocol), question 1 | typing dots first, then the text grew in place (3 distinct lengths), caret shown, **same bubble element from dots to final answer**, page scrollY stayed 0, 2 bold + 1 citation chip rendered, 0 raw `**` |
| Same, question 2 in the same chat ("And what about for the mid semester ones?") | answered correctly (75% per course, page 29); before the fix it said "could not find" |
| First word | 1.2-1.8 s on simple questions; **6.4 s on a long MBA answer** (hidden reasoning time; streaming cannot remove it) |

**Findings**
1. *Fixed:* retrieval ignored the conversation, so follow-up questions lost their context while the LLM kept it (ADR-016). Verified live and in the browser.
2. *Fixed:* answers showed raw markdown (`**bold**`, `- ` lists). A safe in-repo renderer now builds React elements (ADR-017).
3. *Changed, cause not proven:* the "chat slides up and everything goes white" glitch. In the browser the page behind the widget never moved (the widget is `position: fixed`), so my first theory (page scroll) was not the cause. Likely causes were the smooth-scroll animation inside the message list plus a blank wait for the whole answer. Both are gone: instant container-only scrolling that follows the text, and streaming from the first word with one stable bubble. If you still see it, send me what the screen does.
4. *Fixed:* a trace field named `first_token_ms` was blanked by the redaction rule for keys containing "token"; the field is now `ttft_ms`.
5. *Open:* chat history lives in the backend's memory (ADR-006), so it resets when the server restarts (it did, several times, while I was working). The screen keeps your messages across a page refresh, but not across a server restart. A persistent history is a small opt-in feature if you want it.
6. *Done:* your four generated images are wired in as optimised JPEGs (10 MB of PNG became about 660 KB; originals backed up in the git-ignored `data/private/home-originals/`).
7. *Recommendation:* set `LLM_REASONING_EFFORT=low` in `.env` to cut the first-word time of longer answers.

---

## Phase 2 - RAG over a local folder, live on the real documents (2026-11-24)

| Command / check | Result |
|---|---|
| `pytest` (full) | **272 passed** (100 new for Phase 2); `ruff` clean; secret scan passed |
| `scripts/sync_local_once.py --dry-run` | 6 files parsed locally; 1,988 chunks, ~399k tokens, est. $0.008; nothing sent |
| `scripts/sync_local_once.py` (real) | seen 6, indexed 6, failed 0; **25 embedding calls, 379,786 tokens, about $0.0076** |
| Second `sync_local_once.py` | skipped 6, **0 embedding calls**, $0 (AC-06.1 live) |
| Re-sync after excluding `SYNTHETIC_*` | 3 placeholders deleted from the index, $0 |
| FAQ page added | indexed incrementally: 1 file, 1,647 tokens, 3 files skipped |
| Live questions (Model 2, port 8000) | attendance 85% / 75% cited to the handbook (pages 29, 47); MBA eligibility and fees from the right spreadsheet row; MBA application dates from the FAQ; exam dates from the REAL calendar (page 10) with an honest "not a complete schedule"; the cafeteria WiFi question refused with no LLM call |

**Findings (all fixed unless stated)**
1. *Fixed:* placeholder documents in the same folder were answering real questions (exam dates came from `SYNTHETIC_academic_calendar`). Now excluded by default (`LOCAL_DOCS_INCLUDE_SYNTHETIC=false`), with a test.
2. *Fixed:* spreadsheet rows split across chunks lost which course they described. Rows are now sections with a repeated identity prefix.
3. *Fixed:* the text decoder tried UTF-16 before Windows-1252 and silently produced garbage for cp1252 files (found by a unit test).
4. *Open (design choice):* "I paid the fee but my application status shows incomplete" is routed to the personal status path and asks the user to verify, although the FAQ has a general answer.
5. *Note:* Model 2 answers cost about $0.0001-0.0005 and took 2-8 s (reasoning models are slower on long answers).

**Needs you:** add `LOCAL_DOCS_INCLUDE_SYNTHETIC=false` and `INTENT_LLM_FALLBACK=true` to `.env.example` (the repo's deny rules stop me from editing that file).

---

## LLM intent fallback, Evidently in the project venv, trace-redaction fix (2026-11-24)

| Command / check | Result |
|---|---|
| `pip install -r backend/requirements-eval.txt` into `backend/.venv` | Installed (evidently 0.7.23, pandas 2.3.3); no existing package changed |
| `pytest` (full) | **All pass, no expected failures left** (the phrasing xfail was replaced by a check of the recorded live result) |
| `ruff check app tests ../scripts` | All checks passed |
| `scripts/evidently_report.py` with `backend/.venv` | Adversarial and parity reports build; exit 0 |
| `scripts/eval_intent_fallback.py --save-baseline` (live, `gpt-6-luna`, run twice) | **60/60 routed correctly, gap 0.00** (rules only: gap 1.00); 26 calls, 0 errors, about $0.0009, about 1.3 s per call |
| Adversarial suite | 51 structural cases incl. 6 new classifier-manipulation cases (adv-049..054): all pass, 0 critical breaches |

**What changed:** a gated, label-only LLM fallback in `classify_intent` (ADR-015). Rules still run first; the LLM is asked only when the rules fall through AND the
message looks personal; it can only return one of five labels; any failure means "normal question"; identity checks, the cooldown and the registered-recipient rule are
untouched. `usage.intent_llm_called`, the trace fields and the `handled_by` label say when it ran. Switch: `INTENT_LLM_FALLBACK` (default on).

**Found and fixed on the way:** trace redaction masked every key containing "token", so `input_tokens` and `output_tokens` have been blanked in all trace lines since
Phase 0 (no token or cost tracking from traces). Now only numeric `*_input/output/prompt/completion/total_tokens` counts are exempt; `session_token`, `applicant_token`,
`api_key` and similar stay redacted (tests pin both sides).

**Needs you:** add `INTENT_LLM_FALLBACK=true` to `.env.example` (this repo's deny rules stop me from reading or editing that file).

---

## Phase 7 (7.0, 7.3, 7.6) - Evidently spike, adversarial suite, parity audit (2026-11-24)

| Command / check | Result |
|---|---|
| `pip install evidently==0.7.23` in a **throwaway** venv | Installed; needs `pandas<3` (pandas 3 breaks `import evidently`); 4 unused compiled modules blocked by Windows Application Control; `litellm` resolves next to `openai` 3.x |
| `pytest` (backend, full) | **201 passed, 1 expected failure** (was 90 passed) |
| `ruff check app tests ../scripts` | All checks passed |
| `scripts/check_secrets.py` | Passed |
| Adversarial suite: 45 structural cases through the real graph | 45/45 pass, **0 critical breaches** |
| `scripts/evidently_report.py adversarial` / `parity` (throwaway venv) | HTML + JSON reports built; exit 0 on the real run; exit 1 when a critical breach or a slice regression is injected |

**Findings**
1. *Fixed:* a poisoned retrieved passage could forge the context delimiters (`<<<` / `>>>`). `neutralise_delimiters()` added, prompt version `rag-v2` (Models 2 and 3 share it). Regression test in `tests/unit/test_prompts_and_citations.py`.
2. *Open (strict xfail):* the deterministic intent rules route typo'd and Hinglish messages to general Q&A (0% correct) while ALL-CAPS text is 100% correct. Fails safe, but those students cannot reach interview, status or email help.
3. *Documented:* Cyrillic look-alike characters evade the "unsupported action" regex (adv-031); harmless because the LLM path has no tools, so the guarantee comes from capabilities, not from the regex.

Not done: the live-LLM variant of the adversarial suite, Evidently inside `backend/.venv`, the CI workflow (7.5), applicant-side fairness slices.

---

## Phase 1 - install, run the integration suite (2026-11-23)

Environment: Windows 11, Python 3.12.10, Node 24.13.0 / npm 11.6.2. Every row below was run in the Phase 1 session.

| Command | Result |
|---|---|
| Diff root `ARCHITECTURE.md`, `PRD.md`, `REVIEW_OF_STARTER_PACK.md` against `docs/` | Byte-identical (same SHA-256); root copies deleted |
| `git init -b main` + initial commit | 126 files; `.env` was the only ignored file; nothing forbidden staged |
| `python -m venv backend/.venv`; `pip install -r requirements-dev.txt` | Installed (SQLAlchemy 2.1.9 resolved) |
| First `pytest` | **Collection error**: `import sqlalchemy` failed - Windows Application Control blocked SQLAlchemy 2.1.9's compiled `.pyd` files |
| `pip install "sqlalchemy==2.0.58"` | Installed; imports fine (inside the declared `>=2.0.36,<2.2` range) |
| `pytest` (second run) | One collection error naming `ormsgpack` (also Application Control). It did not reproduce on three direct re-imports and the next run; treat it as an intermittent environment block |
| `pytest` (final, after fixes) | **90 passed** in 3.31 s, 0 skipped (60 unit + 29 integration + 1 new regression test) |
| `ruff check app tests ../scripts` | First run **14 findings** (9 `UP017`, 1 `SIM108`, 4 false-positive `S106/S107` on a parameter named `token_param`); all fixed; final run: **All checks passed** |
| `pip freeze` -> `backend/requirements.lock` | 131 lines; SQLAlchemy 2.0.58 recorded |
| `npm install` (frontend) | 69 packages, 0 vulnerabilities; `package-lock.json` created |
| `npm run build` (`tsc --noEmit && vite build`) | Passed, no TypeScript errors (Vite 7.3.8, 34 modules) |
| `python scripts/seed_demo_db.py --yes` | First run **failed** (`unable to open database file`: `storage/` did not exist). After the fix: **Seeded 10 SYNTHETIC applicants** |
| `python scripts/export_graph_diagram.py` | Wrote `docs/graph.mmd` (15 nodes) |
| `python scripts/check_secrets.py` | First run **failed** only because a developer's git-ignored `.env` counted as a forbidden file. After the fix: **passed**. Six throwaway-repo cases confirmed it still fails for a non-ignored `.env`, an ignored `credentials.json`, no git repo, a key-shaped string, and a nested `.env` |
| Non-LLM smoke test (in-process `TestClient`, temp DB/outbox/traces) | Passed - see below |
| Live smoke test: real `uvicorn` on port 8011, temp DB/outbox/traces, simulated email, updated OpenAI key | **Model 1 answered** (`gpt-6-luna`, 148 in / 74 out tokens, 2.2 s, est. $0.00005) with the not-grounded notice; Model 2 gave the honest "no documents indexed" reply (no LLM call); Model 3 returned 503; verify/interview/resend/cooldown behaved as designed; 6 trace lines with no message text and no raw email |
| OpenAI models / deprecations / reasoning pages read | `gpt-6-luna` confirmed; details in `docs/TECHNICAL_REFERENCES.md` |

### Fixes made

- **Seed script failed on a clean checkout.** `make_engine()` now creates the SQLite folder (previously only `init_db()` did, and the seed script drops tables first). Regression test: `tests/integration/test_seed.py`.
- **Ruff.** `timezone.utc` -> `datetime.UTC`; ternary in `mask_email`; renamed the `token_param` parameter to `output_limit_field` (it names an API field, not a credential). No behaviour change.
- **`tzdata` declared** in `requirements.txt` for Windows; it was only present through a transitive dependency.
- **`scripts/check_secrets.py`** tolerates the root `.env` only when `git check-ignore` says it is ignored; everything else still fails (fails closed without git).
- **No integration test or invariant needed changing.**

### Non-LLM smoke test (what it showed)

Verification is case-insensitive and a wrong email gets a generic 401. "When is my interview?" without verification asks to verify; verified, it answers from the DB (no LLM). The first "I have not received my interview email" is `simulated` and writes one outbox file addressed to the registered email from the DB; the immediate repeat is `not_eligible / cooldown_active`. Model 3 returns 503 `model3_not_configured`. Traces contained no message text and no raw email.

### Not done / open

- **Resolved after the first report:** the first Model 1 request was rejected (`provider_auth_failed`) because the key then configured was not valid. My attempt to blank the key for that run did not work (on Windows an empty environment variable is removed, not blanked), so the request used the configured key and failed authentication (no tokens used). After the key was updated, the live smoke test above succeeded. `.env` was never read.
- The UI was not clicked through by a human; the live test drove the same HTTP API the UI uses.
- `LLM_REASONING_EFFORT=low` / `LLM_MAX_OUTPUT_TOKENS=4000` remains a recommendation from OpenAI's docs; the configuration in use did not hit `empty_completion`.
- Retrieval is still `NullRetriever`; Drive sync, SMTP, Models 2/3 retrieval are Phases 2-6.

### Setup items that need you

- `.env`: `OPENAI_API_KEY` (a valid one), `OPENAI_CHAT_MODEL=gpt-6-luna`, `LLM_REASONING_EFFORT=low`, `LLM_MAX_OUTPUT_TOKENS=4000`, leave `LLM_TEMPERATURE` unset; `APP_SECRET_KEY`; `ADMIN_API_KEY`.
- To rebuild the environment exactly: `pip install -r backend/requirements.lock` (a fresh `requirements-dev.txt` install would pick SQLAlchemy 2.1.9 again, which this machine blocks).
- Phase 3: Google Cloud project, service account, shared Drive folder ID. Phase 5 (optional): SMTP sandbox. Phase 6: Hugging Face, Colab GPU, Modal.

---

## Phase 0 - base repository (2026-11-20, generating environment)

Implemented: backend skeleton (settings, SQLite models + seed, fixed repositories, one OpenAI-compatible client,
LangGraph graph with 15 nodes, FastAPI routes, JSONL tracing with redaction, simulated email provider), React UI,
synthetic data and eval sets, docs, and the Claude Code layer (CLAUDE.md, skills, permissions).

That environment had no network for installs, so only `pytest tests/unit` (60 passed), `compileall`, the secret scan
and packaging were run; integration tests, `ruff` and `npm run build` were first executed in Phase 1 (above).
