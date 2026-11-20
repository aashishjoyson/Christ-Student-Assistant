# Model Comparison Report

Fill this from `storage/eval/<run_id>/summary.json` (Phase 7). Do not enter numbers that were not measured.

## 1. Configuration

| Field | Model 1 - Direct LLM | Model 2 - LLM + RAG | Model 3-base (ablation) | Model 3 - LLM + RAG + PEFT |
|---|---|---|---|---|
| Provider | | | model3-endpoint | model3-endpoint |
| Chat / base model ID | | (same as Model 1) | | (same base as ablation) |
| Adapter ID @ revision | n/a | n/a | none | |
| Retrieval | No | Yes | Yes | Yes |
| Embedding model / top-k / max distance | n/a | | (same as Model 2) | (same as Model 2) |
| Prompt version | direct-v1 | rag-v1 | rag-v1 | rag-v1 |
| Decoding params sent | | | | |
| Eval set + size | | | | |
| Run ID / date | | | | |

## 2. Academic Q&A results (synthetic set; add a real-document section when available)

| Metric | Model 1 | Model 2 | Model 3-base | Model 3 | Notes |
|---|---:|---:|---:|---:|---|
| Fact match (answerable) | | | | | |
| Citation hit (expected source cited) | n/a | | | | |
| Retrieval hit@k | n/a | | (same) | (same) | shared retriever |
| Correct refusal (unanswerable) | | | | | |
| Disclaimer present (institutional Qs) | | n/a | n/a | n/a | |
| Human-rated relevance (1-5) | | | | | reviewer(s): |
| Human-rated faithfulness (1-5) | | | | | |
| Latency p50 / p95 (s) | | | | | Model 3 excludes cold start? |
| Avg input / output tokens | | | | | |
| Est. cost per query (USD) | | | | | prices checked on: |

## 3. Workflow results (shared deterministic tools - not an LLM comparison)

| Case set | Expected intent correct | Expected action status correct | Emails to non-registered address |
|---|---:|---:|---:|
| workflow_cases.jsonl | | | must be 0 |

## 4. Observations

- Model 1 - strengths / weaknesses / failure examples:
- Model 2 - retrieval or citation failures:
- Model 3 vs Model 3-base - what the adapter changed (format, refusals, verbosity):
- Model 3 vs Model 2 - combined effect of backbone + adapter:

## 5. Validity and limitations

- Models 1 and 2 used the same model ID: yes / no.
- Model 3 backbone differs from Models 1/2; the PEFT effect is read from Model 3 vs Model 3-base only.
- Synthetic documents are simpler than real ones; small sample sizes - report counts, not just percentages.
- Hosted model IDs can change or be retired; results are tied to the run date.

## 6. Recommendation

Choose on measured grounding, citation accuracy, refusal behaviour, latency, cost and operational effort.
Do not default to the most complex configuration.
