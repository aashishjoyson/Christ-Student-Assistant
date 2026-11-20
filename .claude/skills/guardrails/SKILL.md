---
name: guardrails
description: Review the current diff against the project's safety and experimental-validity invariants. Use after implementing a phase or any change to graph nodes, repositories, email, LLM clients or prompts.
disable-model-invocation: true
---

# Guardrail review

Inspect `git diff` (and new files) and check every item. Report each as OK / VIOLATION (file:line, why) / N/A.

Model paths
- [ ] Model 1 path still has no retriever call; Models 1 and 2 still share one client and model id.
- [ ] Models 2 and 3 share `retrieve_context` and the same prompt builder/version.
- [ ] No code path returns another model's answer for `rag_peft`; unconfigured Model 3 still yields 503.
- [ ] `handled_by` is accurate for every new response path.

Data access
- [ ] No SQL/ORM queries on applicant tables outside `app/db/repositories`.
- [ ] Every repository function touching applicant data filters by the verified `applicant_id`.
- [ ] No name-based or free-text applicant search was added.

Email
- [ ] Recipient and template fields are read from the DB inside `send_interview_email`; nothing from the message, LLM or state.
- [ ] Reservation (UNIQUE key) happens before sending; every outcome is recorded; `sent` only on provider acceptance.
- [ ] Real sending still requires `EMAIL_SEND_ENABLED` and the allowlist.

Privacy and secrets
- [ ] No applicant details enter `history`, traces or logs (masking/redaction intact).
- [ ] No secrets, tokens, real documents, databases or adapters added to the repo; `.env` not read.

Architecture
- [ ] `app/domain` still imports only the standard library.
- [ ] New concrete implementations are constructed only in `app/container.py`.
- [ ] New settings exist in both `app/core/config.py` and `.env.example`.
- [ ] Tests cover the new behaviour and use fakes for external services.

End with a one-paragraph verdict and the exact fixes required, if any.
