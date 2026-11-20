# Build report - Phase 0 base repository

Generated 20 November 2026.

## What is implemented

- Full backend skeleton: settings, SQLite models + seed, fixed repositories, one OpenAI-compatible client,
  LangGraph graph (15 nodes, pure routing, checkpointed history), FastAPI routes (health, chat, verify, admin status),
  JSONL tracing with redaction, simulated email provider.
- Model 1 works with an OpenAI key. Model 2/3 return honest "no documents indexed" answers (retriever arrives in
  Phase 2). Model 3 returns 503 until its endpoint is configured.
- Applicant verification (signed token, rate limit), status and interview lookups, and the complete resend workflow
  (policy, UNIQUE reservation, send, audit, templated response).
- React UI: model selector with "Not configured", chat, citations, Model 1 notice, action status, node path, verify panel.
- Synthetic applicants, synthetic sample documents, evaluation sets.
- Docs: PRD v3, ARCHITECTURE v3, DECISIONS, IMPLEMENTATION_PLAN, REVIEW_OF_STARTER_PACK, TECHNICAL_REFERENCES,
  setup guides, comparison template. Claude Code layer: CLAUDE.md, skills, permissions.

## Commands run in the generating environment

| Command | Result |
|---|---|
| `pytest tests/unit` (backend) | **60 passed** |
| `python -m compileall app tests ../scripts` | OK (all files compile) |
| Import of all Pydantic schemas | OK |
| `python scripts/check_secrets.py` | Passed |
| `python scripts/package_repo.py` | ZIP produced |

## Not run here (do these first in Phase 1)

The generating environment had no network access for package installation, so FastAPI, SQLAlchemy, LangGraph,
the OpenAI SDK and Node packages were unavailable. Therefore:

- `tests/integration/*` (29 tests covering all 12 required behaviours) were written but **not executed**.
- `ruff check` and `npm run build` were **not executed**.

Expect a few small fixes when you first run them (version-specific API details). Phase 1 in
`docs/IMPLEMENTATION_PLAN.md` starts exactly there.

## Setup items that need you

- `OPENAI_API_KEY` and confirmation of the `OPENAI_CHAT_MODEL` id; `APP_SECRET_KEY`; `ADMIN_API_KEY`.
- Phase 3: Google Cloud project + service account + shared Drive folder ID.
- Phase 5 (optional): SMTP sandbox credentials and an allowlist.
- Phase 6: Hugging Face account (private adapter repo), Colab GPU session, Modal (or HF Endpoints) account.
- Real university documents uploaded to Drive (never to Git).
