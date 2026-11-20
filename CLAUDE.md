# CLAUDE.md - CU Student Helpdesk AI

Academic prototype: React chat UI + FastAPI + LangGraph. Three honestly labelled model paths
(Model 1 direct LLM, Model 2 LLM+RAG, Model 3 RAG + LoRA endpoint), Drive -> Chroma ingestion,
synthetic applicant DB, and one controlled action (interview email resend).

Read before changing behaviour: `docs/PRD.md` (what), `docs/ARCHITECTURE.md` (how),
`docs/IMPLEMENTATION_PLAN.md` (phases, current status), `docs/DECISIONS.md` (why).
Work one phase at a time with `/phase <n>`; finish with `/verify` and `/guardrails`.

## Commands (run from repo root unless noted)

- Backend setup: `python -m venv backend/.venv` then install `backend/requirements-dev.txt` into it
- Run API: `cd backend && uvicorn app.main:app --reload --port 8000`
- Tests: `cd backend && pytest` (unit only: `pytest tests/unit`)
- Lint: `cd backend && ruff check app tests ../scripts`
- Frontend: `cd frontend && npm install && npm run dev` · build/typecheck: `npm run build`
- Seed synthetic DB: `python scripts/seed_demo_db.py --yes`
- Secret scan: `python scripts/check_secrets.py` · Package: `python scripts/package_repo.py`
- Graph diagram: `python scripts/export_graph_diagram.py`

## Architecture map

- `backend/app/domain/` - PURE stdlib logic (intents, prompts, chunking, citations, notification policy, tokens, masking). No framework, DB or network imports here.
- `backend/app/graph/` - LangGraph state, pure routing, nodes, builder. Nodes depend on protocols in `GraphDeps`.
- `backend/app/db/repositories/` - the ONLY place that queries applicant data.
- `backend/app/llm/` - one `OpenAICompatibleChatClient` for OpenAI, OpenRouter and the Model 3 endpoint.
- `backend/app/rag/` - `Retriever` / `DocumentSource` protocols (Chroma + sources arrive in Phases 2-3).
- `backend/app/container.py` - the only place concrete implementations are constructed.
- `backend/tests/unit` (pure) and `backend/tests/integration` (real SQLite + LangGraph, fake LLM/retriever/email).

## Non-negotiable invariants (tests exist for most; never weaken them)

1. Model 1 never calls the retriever. Models 1 and 2 use the same client/model. Models 2 and 3 use the same retrieval and prompt.
2. Model 3 never falls back: unconfigured -> 503 `model3_not_configured`; endpoint error -> 5xx. Never label another model's output as Model 3.
3. The LLM never writes or runs SQL. Applicant data only via fixed functions in `db/repositories`, always scoped by the verified `applicant_id`.
4. Email recipient and every email field come from the database inside `send_interview_email`. Never from the message, the LLM, or graph state.
5. Reserve (UNIQUE idempotency key) before sending; record every attempt; `sent` only after provider acceptance. Default provider is console (simulated).
6. Real sending requires `EMAIL_SEND_ENABLED=true` AND an allowlisted recipient.
7. Applicant answers never enter LLM history (placeholder only); traces contain no message text by default and are redacted.
8. No university facts in code or prompts; facts come from indexed documents. Synthetic data is labelled SYNTHETIC.
9. No secrets in code, tests or docs. Never read or print `.env`. Never commit credentials, databases, Chroma data, adapters or real documents.
10. No local LLM inference. Tests never call paid APIs, Google, or a mail server - use `tests/fakes.py`.

## Conventions

- Python 3.11+, type hints everywhere, Pydantic for API schemas, SQLAlchemy 2.0 typed models, timezone-aware UTC datetimes (`UTCDateTime` rejects naive values).
- Keep modules small and explicit; prefer a plain function over a new abstraction. Comment the *why* of non-obvious logic.
- All model/provider IDs and tunables live in `app/core/config.py` and `.env.example` - nowhere else. Add new env vars to both.
- When changing a prompt, bump its version in `app/domain/model_modes.py`.
- New behaviour needs tests: pure rules in `tests/unit`, wiring in `tests/integration`. Write the failing test first for safety rules.
- Update `docs/IMPLEMENTATION_PLAN.md` checkboxes and `docs/TECHNICAL_REFERENCES.md` (re-check log) when a phase adopts a new API or version.
- Use official, current docs for LangGraph, OpenAI, Google Drive, Chroma, PEFT, vLLM; record what you checked.

## Definition of done (every phase)

`ruff` clean · `pytest` green · `npm run build` green (if frontend touched) · `check_secrets.py` passes ·
docs updated · acceptance criteria for the phase demonstrated · short summary of what changed and what the user must configure.
