# Build report

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
