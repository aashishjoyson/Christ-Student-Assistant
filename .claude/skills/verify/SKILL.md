---
name: verify
description: Run the project's quality gate (ruff, pytest, frontend build, secret scan) and report results. Use before every commit and at the end of every phase.
---

# Verify

Run each step from the repo root and report pass/fail with the key output. Fix failures you can reproduce, then re-run.

1. Lint: `cd backend && ruff check app tests ../scripts`
2. Tests: `cd backend && pytest -q`
3. Frontend (only if `frontend/` changed or a build was never run): `cd frontend && npm run build`
4. Secret scan: `python scripts/check_secrets.py`
5. Confirm no forbidden files are staged: `git status` must not show `.env`, `secrets/`, `storage/`, `*.db`, Chroma data, adapters or real documents.

Summarise as a short table: step, result, notes. Do not mark anything as passing unless you ran it in this session.
