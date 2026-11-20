# CU Student Helpdesk AI - base repository

Academic prototype for an LLM / RAG / PEFT / LangGraph / LLMOps project: a student-helpdesk chatbot with
three selectable model configurations, Google Drive document ingestion, a synthetic applicant database
and a controlled interview-email workflow.

> Not an official Christ University service. All applicant data and sample documents are **synthetic**.

| Mode | Label | What it is |
|---|---|---|
| `direct` | Model 1 - Direct LLM | Hosted LLM only (not grounded) |
| `rag` | Model 2 - LLM + RAG | Same hosted LLM + retrieved documents with citations |
| `rag_peft` | Model 3 - LLM + RAG + PEFT | Same retrieval + LoRA-adapted open model on a cloud endpoint |

## Status

This is the **Phase 0 base**: the full skeleton runs end to end. Phases 1-8 are planned in
`docs/IMPLEMENTATION_PLAN.md` and are meant to be built with Claude Code (`/phase <n>`).

| Works now | Arrives in |
|---|---|
| LangGraph routing, Model 1 (with an API key), applicant status/interview lookups, signed verification, resend workflow (simulated email + audit), traces, UI | Phase 0 (done) |
| Model 2/3 answer "no documents indexed" until ingestion exists | Phase 2 (local folder RAG) |
| Drive sync endpoint returns 501 | Phase 3 |
| Model 3 shows "Not configured" | Phase 6 (train + deploy adapter) |

## Quick start

Prerequisites: Python 3.12 (3.11-3.13), Node.js 20+, an OpenAI API key.

### macOS / Linux
```bash
cp .env.example .env                 # then edit: OPENAI_API_KEY, APP_SECRET_KEY, ADMIN_API_KEY
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/python scripts/seed_demo_db.py --yes
cd backend && .venv/bin/pytest && cd ..
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000     # terminal 1
cd frontend && npm install && npm run dev                              # terminal 2
```

### Windows (PowerShell)
```powershell
Copy-Item .env.example .env          # then edit it
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements-dev.txt
backend\.venv\Scripts\python scripts\seed_demo_db.py --yes
cd backend; .venv\Scripts\pytest; cd ..
cd backend; .venv\Scripts\uvicorn app.main:app --reload --port 8000   # terminal 1
cd frontend; npm install; npm run dev                                  # terminal 2
```

Open http://localhost:5173. API docs: http://127.0.0.1:8000/docs.

## Try it

- Model 1: "What is the minimum attendance requirement?" -> answer with a not-grounded notice.
- Verify (right panel): `CUAPP-DEMO-0001` / `aarav.demo@example.com`, then:
  - "What is the status of my application?"
  - "When is my interview?"
  - "I have not received my interview email" -> simulated resend; the message is written to `storage/outbox/`.
  - Repeat it -> "not eligible" (15-minute cooldown).
- Other seeded cases: `0003` (no interview), `0004` (rescheduled), `0005` (completed), `0006` (cancelled).
- Open "How this was handled" under any answer to see the LangGraph node path.
- Traces: `storage/traces/requests.jsonl`.

## Building the rest with Claude Code

1. Open this folder in VS Code and start Claude Code in the terminal (`claude`).
2. Claude reads `CLAUDE.md` automatically. Start with `/phase 1` (install + run the full test suite + real Model 1).
3. Continue `/phase 2` ... `/phase 8`. After each: `/verify`, `/guardrails`, commit.
4. `/package` builds the clean submission ZIP.

## Repository map

```text
backend/app/domain      pure rules (unit-tested)       backend/app/graph   LangGraph state, nodes, routing, builder
backend/app/db          models, seed, fixed queries    backend/app/llm     one OpenAI-compatible client
backend/app/rag         retriever/source interfaces    backend/app/api     FastAPI routes
backend/tests           unit + integration (fakes)     frontend/src        React UI
data/                   synthetic applicants, docs, eval sets
docs/                   PRD, ARCHITECTURE, IMPLEMENTATION_PLAN, DECISIONS, REVIEW, setup guides
scripts/                seed, secret scan, package, graph diagram
.claude/                Claude Code skills (/phase, /verify, /guardrails, /package) and permissions
```

## Demo sequence (final)

1. Same academic question in Model 1, 2 and 3; compare notice, citations and handled-by labels.
2. Upload a new document to the Drive folder, sync, ask about it.
3. Verify a synthetic applicant; status, interview, resend (simulated), cooldown.
4. Show the trace file and the evaluation comparison report.

## Safety defaults

Email is simulated; real sending needs `EMAIL_SEND_ENABLED=true` plus an allowlist. Admin routes are off until
`ADMIN_API_KEY` is changed. Model 3 never falls back to another model. Run `python scripts/check_secrets.py`
before committing.
