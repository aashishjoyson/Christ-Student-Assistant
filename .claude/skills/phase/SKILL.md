---
name: phase
description: Implement one phase of docs/IMPLEMENTATION_PLAN.md end to end (plan, tests, code, docs, verify). Use when the user types /phase followed by a phase number.
argument-hint: "<phase number, e.g. 2>"
disable-model-invocation: true
---

# Implement phase $ARGUMENTS

1. **Load context.** Read `docs/IMPLEMENTATION_PLAN.md` (the "Phase $ARGUMENTS" section and the Phase 0 "Known state"),
   then only the PRD requirements and ARCHITECTURE sections that phase references. Skim the existing code it touches.
   Do not read `.env` or anything in `secrets/` or `storage/`.
2. **Check currency.** For any external API the phase introduces (Chroma, Google Drive, PEFT/TRL, vLLM, Modal, SMTP, MLflow),
   check the current official docs and package versions. Note findings in the re-check log of `docs/TECHNICAL_REFERENCES.md`.
3. **Plan briefly** (files to create/modify, tests to add, risks). If something in the plan conflicts with an invariant in
   `CLAUDE.md`, stop and explain instead of proceeding.
4. **Tests first for rules.** Add failing tests for the phase's acceptance criteria (pure logic in `backend/tests/unit`,
   wiring in `backend/tests/integration` using `tests/fakes.py`). Never call paid APIs, Google or mail servers in tests.
5. **Implement** the smallest clean design that passes. Keep new tunables in `app/core/config.py` + `.env.example`.
   Wire concrete implementations only in `app/container.py`.
6. **Verify** by running the `/verify` checks and fix everything you can reproduce. Never claim a test passed without running it.
7. **Document.** Tick the phase checkboxes in `docs/IMPLEMENTATION_PLAN.md`, update README/setup docs if commands or
   configuration changed.
8. **Report:** what was built, test results observed, anything the user must configure (keys, accounts, files), and
   anything deferred. Suggest a commit message.
