# Model card: CU Student Helpdesk AI (academic prototype)

This card describes the **system** (three answer paths over one shared set of rules), because that is what a student actually meets. Every number comes from a run recorded in
`BUILD_REPORT.md` or `docs/MODEL_COMPARISON_REPORT.md`; where something was not measured, it says so.

## 1. What it is for

A chat widget on a university homepage that answers questions about the university from its own documents (calendar, handbook, programme list, FAQ), and can look up one visitor's
application and interview and resend their interview email. **It is an academic prototype, not an official university service**, and says so in the widget footer.

In scope: questions whose answer is in the indexed documents; a verified applicant asking about their own interview or application status; one controlled action (resend the interview email).
Out of scope, by design: changing any record (grades, fees, attendance, applications, interview slots), legal, medical or wellbeing advice, anything about other people, and any fact that is not in the documents.

## 2. The three paths

| Path | What answers | Grounded in documents? | State |
|---|---|---|---|
| Model 1, direct | hosted `gpt-6-luna`, no documents | No: it opens with "I have not checked official university documents, so this may be inaccurate" | Working |
| Model 2, RAG | the same hosted model plus retrieved passages with citations | Yes | Working, measured below |
| Model 3, RAG + PEFT | an open model (`Qwen/Qwen3-4B-Instruct-2507`) with a LoRA adapter on a cloud endpoint (vLLM on Modal), same retrieval and prompt as Model 2 | Yes | **Trained, deployed and measured** (LoRA r=16, 344 examples, 2 epochs, one Colab T4 run). On the golden set it answered **24 of 30 correctly, against 28 of 30 for Model 2 and for the same base model without the adapter** (section 4): it is the fine-tuned path, not the better one. Unconfigured or cold, it reports an error and never falls back to another model |

Applicant look-ups, the verification step and the email resend are deterministic code, not a model. A model only chooses a route (a single label from a fixed list) when the rules cannot, and never sees applicant data.

## 3. Data

- **Documents (four, all provided by the owner, from Drive):** the academic calendar 2026-27 (PDF), the student handbook 2026-27 (PDF), the programme and fee table (spreadsheet, 312 rows) and a copy of the university's public FAQ page. Facts are never written in code or prompts.
- **Applicants:** six synthetic records, labelled SYNTHETIC. No real applicant data is in the repository or the prototype.
- **Conversation text:** not stored by default. Traces hold no message text. Optional persistent memory (`CHAT_HISTORY_PERSIST`) keeps recent turns for 30 days with emails masked and applicant answers replaced by a placeholder.
- **Model 3 training data:** 371 examples (344 for training, 27 for validation) generated from the same documents by the hosted model as a teacher, with every number checked against the cited passage; passages that prove an evaluation answer are held out. Used for one training run.

## 4. How it was evaluated (and how far to trust it)

Golden set: 38 questions on the four documents (30 answerable, each proven by a literal quote; 8 unanswerable, proven absent). Run on 2026-11-24, model `gpt-6-luna`:

| | Model 1 | Model 2 |
|---|---:|---:|
| Answered correctly (of 30) | 3 (10%) | 28 (93.3%); the accepted baseline run scored 27 (90%) |
| Correctly refused unanswerable questions (of 8) | not applicable | 8 |
| Answers to unanswerable questions that were invented | not applicable | 0 |
| Proving quote reached the model | not applicable | 100% |
| Citation hit | not applicable | 93.3% |
| Median / p95 latency | 1.7 s / 3.4 s | 1.8 s / 3.0 s (the provider was slower later the same day: about 7 s) |
| Cost per question | $0.00006 | $0.00014 |

**Read these with care.** 38 questions is small: one question is 2.6 points, and identical settings moved by about one question between runs. The retrieval settings were tuned on this same set, so the figure is optimistic for
unseen questions; a held-out set has not been built. Answers are checked by deterministic text rules, which count a correct answer worded in an unlisted way as wrong and a correct fact with a wrong extra claim as right.
The weakest area is the fee spreadsheet (1 of 3 correct in the run reported in the comparison report), where many near-identical programmes at different campuses compete.

Model 3 and its ablation were run on the same questions on 2026-11-25 (the four questions that differ are listed in `docs/MODEL_COMPARISON_REPORT.md`, section 6):

| | Model 2 | Model 3 (adapter) | Same base model, no adapter |
|---|---:|---:|---:|
| Answered correctly (of 30) | 28 (93.3%) | **24 (80.0%)** | 28 (93.3%) |
| Correctly refused unanswerable questions (of 8) | 8 | 8 | 8 |
| Invented answers to unanswerable questions | 0 | 0 | 0 |
| Citation hit | 93.3% | 73.3% | 90.0% |
| Median / p95 latency | 1.4 s / 2.1 s | 1.6 s / 2.6 s | 1.5 s / 3.3 s |

The adapter changed the style it was trained for (answers about half as long, one citation) but did not improve accuracy: the four questions it lost against its own base model are all calendar dates (a wrong month, one of two dates reported, one refusal).
It was measured once, at temperature 0.2, on 38 questions: a four-question gap is a hint (exact sign test p = 0.125), not proof, and its run-to-run variation is unknown. Nothing was retrained or tuned after this result (ADR-025), and the adapter was not promoted.

Safety and robustness checks that run on every push (no key, no network): 51 structural adversarial cases through the real graph (prompt injection, forged context, identity bypass, email redirection and flooding, cross-applicant access, injected SQL, filter evasion, classifier manipulation and more), **0 critical breaches**;
7 further cases need a live model and have **not been run**. Phrasing fairness: the share of messages routed to the intended path was 100% in every phrasing slice (formal, informal, typos, non-native English, Hinglish, emoji) in one live run of 60 messages, against 0% for typos and Hinglish with rules alone; that is a recorded single run of a non-deterministic model, not a guarantee.

## 5. Known limits and risks

| Risk | What the system does | What is left |
|---|---|---|
| Wrong or stale answers | answers cite passages; "could not find" when the passages lack the answer; the index refreshes itself from Drive and an alert fires if it goes stale | a model can still misread a passage; the golden set does not cover every document |
| A model inventing facts | the prompt forbids it; evaluation counts unsupported answers (0 of 8) | a small sample |
| Model 3 gives a wrong or partial date | labelled as the fine-tuned path, never substituted for another model, and measured against Model 2 and its own base model; it still refused 8 of 8 unanswerable questions and invented none | 4 of 11 calendar questions wrong or incomplete in the one run; the cause was not investigated; prefer Model 2 for dates |
| Prompt injection in documents or messages | passages and messages are treated as data; delimiters cannot be forged; the model has no tools | not a proof; new attack styles appear |
| Private data | applicant details only through fixed queries scoped to the verified applicant; the model never writes SQL or sees details; email goes only to the registered address from the database | the verification step is **demo-level** (application id plus registered email); a real deployment needs the university's single sign-on |
| Misuse of the email action | reserved before sending, one send per cooldown window; the recipient is read from the database and must be on the allowlist; real sending over SMTP uses TLS with certificate checks, one plain address and no line breaks in headers; simulated by default | "sent" means the server accepted the message, not that it was delivered; delivery was tried with one Gmail account and one university address only |
| Abuse and cost | per-client rate limits on chat, verification and ratings; per-request cost recorded and alerted on | the limits assume the proxy forwards the client address |
| Unequal treatment by phrasing | deterministic rules plus a label-only model fallback close the measured gap | measured on 60 synthetic messages |
| Documents and images | the UI uses AI-generated illustrations and a crest copied for the demo | see `LICENSE_NOTES.md` (repository root); replace before any public use |

## 6. Operation

Traces (no text), a monitoring report with alerts and drift checks, thumbs up/down with fixed reasons, an admin page, retention rules, and a promotion policy that stops a change from replacing the baseline if a critical gate regresses
(`docs/PROMOTION_POLICY.md`). Prompt versions and model ids are recorded in every trace. Rolling back means reverting the commit and, if one was promoted, the baseline file.

## 7. Intended maintenance

Re-run `scripts/run_evaluation.py` whenever a document set, a prompt, a model, a retrieval setting or a parser changes (after an adapter or dataset change use `--modes rag,rag_peft,rag_peft_base` and apply rule 7 of the promotion policy); re-prove the golden set (`scripts/check_golden_set.py`) when documents change; grow the golden set and add a held-out
half before quoting the headline number; refresh the model price table (`app/domain/pricing.py`) and re-check model deprecations (the OpenAI models page listed several retirements for December 2026 and January 2027).
