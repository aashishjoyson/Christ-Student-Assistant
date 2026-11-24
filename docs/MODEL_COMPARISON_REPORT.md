# Model comparison report (measured, 2026-11-24)

Filled from `storage/eval/eval-20261124-134100-7304c1/summary.json` (git-ignored; the numbers below are copied from it). Template: `MODEL_COMPARISON_TEMPLATE.md`.
Nothing here was estimated. **Model 3 (LoRA endpoint) does not exist yet, so its columns are empty by design.**

## 1. Configuration

| Field | Model 1 - Direct LLM | Model 2 - LLM + RAG | Model 3 |
|---|---|---|---|
| Provider / model | OpenAI `gpt-6-luna` | the same model (ADR-003) | not built (Phase 6) |
| Reasoning effort / max output tokens | `low` / 800 | same | - |
| Retrieval | none | Chroma, `text-embedding-3-small`, top-k 8, max distance 0.75, lexical re-rank weight 0.30 over a pool of 150 | - |
| Prompt version | `direct-v1` | `rag-v2` | - |
| Eval set | `data/eval/academic_real.jsonl`: 38 questions (30 answerable with proof quotes, 8 unanswerable proven absent) | same | - |
| Documents | 4 real files from Drive: academic calendar PDF, handbook PDF, courses XLSX, website FAQ | same | - |
| Run | `eval-20261124-134100-7304c1` | same run | - |

## 2. Results (one run per mode; n = 38)

| Metric | Model 1 | Model 2 | Notes |
|---|---:|---:|---|
| Answer accuracy (answerable, all expected facts present, not a refusal) | **3 / 30 = 10%** | **28 / 30 = 93.3%** | a repeat run of Model 2 gave 93.3% again |
| Citation hit (the expected source was cited) | n/a | 93.3% | |
| Retrieval hit@8 / MRR | n/a | 100% / 0.944 | shared by Models 2 and 3 |
| Proving quote reached the model (context recall) | n/a | 100% | a failure with this at 100% is a generation problem, not retrieval |
| Accuracy when the evidence was present | n/a | 93.3% | |
| False refusals (answerable, but "could not find") | n/a | 2 / 30 = 6.7% | |
| Correct refusals (unanswerable) | n/a | 8 / 8 = 100% | |
| Unsupported answers to unanswerable questions | n/a | 0 / 8 | |
| Routed to the documents path | 100% | 100% | |
| Citation numbers valid | 100% | 100% | Evidently critical test passes |
| Latency p50 / p95 | 1.73 s / 3.40 s | 1.80 s / 2.99 s | wall-clock, includes the retrieval embedding for Model 2 |
| Input / output tokens (total over 38) | 5,648 / 3,274 | 50,367 / 965 | |
| Cost per question (USD) | 0.000058 | 0.000145 | `gpt-6-luna` list prices in `app/domain/pricing.py` |

By category (Model 2 accuracy): calendar 11/11, handbook 10/10, FAQ 6/6, **courses 1/3**. Model 1: calendar 2/11, handbook 1/10, FAQ 0/6, courses 0/3.

## 3. How Model 2 got here (each step measured on the same 38 questions)

| Step | Accuracy | What it showed |
|---|---:|---|
| First live run | 70% (21/30) | false refusals 17%; 2 questions routed to the personal-data path; 25 course rows contained pasted CSS |
| + citation/intent/FAQ/calendar/CSS fixes, old retrieval settings | 83% | structure-aware parsing and routing fixes alone were worth +13 points |
| + top-k 8, cut-off 0.75 | 87-90% | the old 0.6 cut-off rejected answerable questions on the old index |
| + lexical re-rank over a pool of 150 | **93%** | proving quote reaches the model 100% of the time (was 90%); MRR 0.90 -> 0.94 |

Noise: identical settings moved by about one question (2.6 points) between runs, so differences of one question are not evidence.

## 4. Observations

- **Model 1 knows nothing about this university.** Its 3 correct answers are general knowledge (Founder's Day, the Kannada Rajyotsava holiday, "your student ID card may also be your library card"), each opened with "I have not checked official university documents, so this may be inaccurate". It also attempts the unanswerable questions, with the same disclaimer, instead of refusing, which is why refusal metrics are only reported for modes that are given documents.
- **Model 2 failures (2 left):** both are the BBA fee questions from the courses spreadsheet (g29 programme fee per year, g30 admission registration fee). Both are refusals ("I could not find this ...") although the passage reached the model. The retrieved rows are many near-identical BBA programmes at different campuses, which is the likely reason the model would not commit (not proven; the run does not log the model's reasoning). Listing every matching campus in the answer, or a structured fee lookup, are the candidate fixes; neither is built.
- **Evaluation limits:** facts are matched by deterministic text rules; a correct answer worded in a way the rules do not list counts as a miss, and an answer with a correct fact plus a wrong extra claim counts as correct. An optional capped LLM judge for faithfulness is planned but not built.
- **Model 3 / ablation:** not measured; cannot be compared until the endpoint exists (Phase 6).

## 5. Validity

- Models 1 and 2 use the same model ID. The golden set is small (38); report counts, not just percentages. Settings were tuned on this same set, so the 93% is optimistic for unseen questions; a held-out set is the next honest step.
- Results are tied to the run date, the model ID and the four documents in Drive at that time.
