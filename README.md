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

Working end to end (see `BUILD_REPORT.md` for what was measured, and `docs/IMPLEMENTATION_PLAN.md` for the plan):

| Area | State |
|---|---|
| Chat: LangGraph routing, Model 1 and Model 2, streaming answers with citations, follow-up questions, applicant verification, controlled interview-email resend (simulated by default) | **Done and measured** |
| Documents: Google Drive folder -> parse -> embed -> Chroma, automatic polling, add/edit/delete handled | **Done, verified live** |
| Evaluation: 38-question golden set proven against the real documents, frozen-configuration runs, promotion gates, CI | **Done**: Model 2 answers about 90-93% correctly, Model 1 about 10% |
| Monitoring and feedback: traces without text, alerts, drift report, thumbs up/down, admin page (`/#/admin`) | **Done** |
| Operations: optional persistent chat memory, rate limits, retention, Docker files | Done; Docker files **not built** (no engine was running) |
| Model 3 (LoRA): dataset builder, notebook, serving file, manifest and endpoint checks, ablation mode | Tooling done; **needs your Hugging Face, Colab and Modal accounts** to train and deploy. Until then Model 3 reports "not configured" and never falls back |

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

## Everyday commands (repo root, backend virtual environment)

| Task | Command |
|---|---|
| Index the Drive folder once (or `--force` after a parser change; `--dry-run` lists only) | `python scripts/sync_drive_once.py` |
| Run the golden-set evaluation (`--modes direct,rag`, `--evidently` for the report) | `python scripts/run_evaluation.py` |
| Compare a run with the baseline, or promote it | `python scripts/compare_eval.py latest` / `--promote --reason "..."` |
| Prove the golden set against the documents | `python scripts/check_golden_set.py` |
| Watch the live system (alerts, drift) | `python scripts/monitor_traces.py` |
| Delete old traces, ratings and stored chats | `python scripts/retention.py --dry-run` |
| Build the Model 3 training set (about 3 cents) | `python scripts/build_peft_dataset.py --dry-run` then `--yes` |
| Check the Model 3 endpoint before calling it Model 3 | `python scripts/check_model3_endpoint.py --ask` |
| Whole system in containers (see `docs/DEPLOYMENT.md`) | `docker compose up --build` |

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
scripts/                sync, evaluate, compare, monitor, retention, PEFT dataset, seed, secret scan, package
deploy/ notebooks/      Model 3 serving (Modal + vLLM) and training (Colab) - written from the docs, not run here
.claude/                Claude Code skills (/phase, /verify, /guardrails, /package) and permissions
```

## Demo

The full show list, in order, with what to say and what to expect, is `docs/DEMO_SCRIPT.md`.

## Safety defaults

Email is simulated; real sending needs `EMAIL_SEND_ENABLED=true` plus an allowlist. Admin routes are off until
`ADMIN_API_KEY` is changed. Model 3 never falls back to another model. Run `python scripts/check_secrets.py`
before committing.
