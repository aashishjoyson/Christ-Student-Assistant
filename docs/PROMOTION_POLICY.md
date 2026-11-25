# Promotion policy: when may a change replace what is running?

"Change" means anything that can alter an answer: a prompt, the hosted model or its settings, retrieval settings (top-k, cut-off, re-rank), the parser or chunker,
the embedding model, the routing rules, and later the LoRA adapter (Model 3). A change is **promoted** when it becomes the new accepted baseline.
The rule is one sentence: *a change is promoted only when a fresh evaluation run, on the same golden set, shows no critical regression against the baseline, and
the reason is written down.*

## 1. The evidence a change needs

| # | Evidence | How it is produced | Blocks promotion? |
|---|---|---|---|
| 1 | Lint, unit and integration tests, adversarial suite, parity audit, frontend build, secret scan all pass | CI (`.github/workflows/ci.yml`), same as `/verify` locally | yes |
| 2 | An evaluation run on the **same golden set** (same file hash) with the change in place | `python scripts/run_evaluation.py --modes direct,rag --evidently` | yes (no run, no promotion) |
| 3 | The run was made on a **committed tree** and had **no errors** | recorded in the run's `config.json` | yes |
| 4 | No **critical** gate regresses against the baseline | `python scripts/compare_eval.py latest` | yes |
| 5 | A prompt change bumps its version (`app/domain/model_modes.py`, `intent_fallback.py`, ...) and has an ADR entry saying why | review | yes |
| 6 | The reason and the numbers are written in BUILD_REPORT.md and, for a decision, `docs/DECISIONS.md` | review | yes |
| 7 | Model 3 / adapter only: it beats its own base model on the same set (the ablation), and passes every safety gate | `--modes rag,rag_peft,rag_peft_base`, read side by side (not scripted: see section 5) | yes |

## 2. The gates (`backend/app/eval/compare.py`)

Run-to-run noise on the 38-question set is about one question (2.6 points), measured with identical settings. Tolerances are set just above that so noise does not fail a run and a real regression does.

| Gate | Rule against the baseline | Critical? | Why |
|---|---|---|---|
| answer accuracy | may drop by at most 0.06 (two questions) | yes | the headline quality number |
| correct refusals | must not drop at all | yes | an unanswerable question must still be refused |
| unsupported answers | must not rise at all | yes | nothing may be invented where the documents are silent |
| citation numbers valid | must stay 100% | yes | a citation must point at a passage the model was given |
| routed to the documents path | may drop by at most 0.03 (one question) | yes | a general question sent to the personal-data path is a bug |
| errors | must not rise | yes | |
| context recall, citation hit, MRR, false refusals | small tolerances | warning | diagnostics: they explain a change, they do not decide it |
| p95 latency, cost per answer | up to x1.5 | warning | one slow call moves p95; a cost jump needs a reason, not a veto |

Reading a result: **FAIL** blocks promotion. **WARN** is printed and must be mentioned in the build report. **note** lines say what changed besides the code (the indexed documents, a prompt version, retrieval settings), because a difference can come from the data and not from the change.
Runs on a different golden set are **incomparable**, not "passed".

## 3. How to promote

```text
python scripts/run_evaluation.py --modes direct,rag --evidently        # on a committed tree
python scripts/compare_eval.py latest                                   # exit 0 = no critical regression
python scripts/compare_eval.py latest --promote --reason "what changed and why"
git add data/eval/baselines && git commit                               # the baseline is reviewed like code
```

`--promote` refuses without a reason, on a failing comparison, on a dirty tree, on a run with errors, and on a different golden set (unless `--allow-new-golden`).
The current baseline records which run it came from, the commit, the golden-set hash, the index fingerprint and the reason.

## 4. Roll back

Revert the commit that changed the behaviour and, if the baseline was promoted with it, the baseline file. The previous baseline is in git history. Prompt and model ids are versioned in every trace, so a rolled-back answer path is identifiable.

## 5. Limits you should know about

- **Small sample.** 38 questions; one question is 2.6 points. Do not read a one-question difference as a trend. The settings were tuned on this same set, so the absolute figure is optimistic for unseen questions: **build a held-out set before quoting it**.
- **Deterministic matching.** A correct answer worded in a way the accepted wordings do not list is counted wrong; a correct fact plus a wrong extra claim is counted right. The optional capped LLM judge for faithfulness is planned, not built.
- **Live evaluation is manual.** `.github/workflows/eval-gate.yml` runs it from the Actions tab and needs secrets (see the file). It has not been executed yet.
- **Rule 7 (adapters) is applied by reading the run, not by a script.** `compare_eval.py` compares one mode with a baseline that holds Model 2 only, so `--mode rag_peft` prints INCOMPARABLE, and no Model 3 baseline exists.
  First application, 2026-11-25 (run `eval-20261125-045830-a4ce98`): the adapter scored 24 of 30 against 28 of 30 for its own base model, so **rule 7 was not met and the adapter was not promoted**. It stays in the app as the fine-tuned path, labelled with what was measured.
- **Branch protection** is a repository setting and is not applied by code. To make CI a real gate: GitHub > Settings > Branches > add a rule for `main` > require status checks `backend (lint and tests)`, `frontend (build and tests)` and `secret scan` (and, if you work through pull requests, require a pull request before merging).

## 6. What CI does and does not do

CI runs everything that needs no key and no network. It does **not** call a model, embed text, read Drive or compare against the baseline: those need credentials and money, so they are the manual workflow above. Fake-LLM tests still prove the harness itself (scoring, config freezing, gates, promotion rules) on every push.
