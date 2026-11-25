# Model comparison report (measured, 2026-11-24 and 2026-11-25)

Sections 1 to 5 are filled from `storage/eval/eval-20261124-134100-7304c1/summary.json` (Models 1 and 2); section 6 from `storage/eval/eval-20261125-045830-a4ce98/summary.json` (Model 2 again, Model 3 and the base-model ablation).
Both folders are git-ignored; the numbers below are copied from them. Template: `MODEL_COMPARISON_TEMPLATE.md`.
Nothing here was estimated. **Model 3 (the LoRA endpoint) was measured once, on 2026-11-25, and did not beat its own base model: section 6 reports it as it came out, and nothing was tuned afterwards (ADR-025).**

## 1. Configuration

| Field | Model 1 - Direct LLM | Model 2 - LLM + RAG | Model 3 |
|---|---|---|---|
| Provider / model | OpenAI `gpt-6-luna` | the same model (ADR-003) | `Qwen/Qwen3-4B-Instruct-2507` + LoRA adapter `cu-helpdesk-lora`, served by vLLM on Modal (section 6) |
| Reasoning effort / max output tokens | `low` / 800 | same | no reasoning setting / 800; temperature 0.2 (Models 1 and 2 send no temperature) |
| Retrieval | none | Chroma, `text-embedding-3-small`, top-k 8, max distance 0.75, lexical re-rank weight 0.30 over a pool of 150 | the same as Model 2 (in the run of section 6 the three modes received identical passages for all 38 questions) |
| Prompt version | `direct-v1` | `rag-v2` | `rag-v2` |
| Eval set | `data/eval/academic_real.jsonl`: 38 questions (30 answerable with proof quotes, 8 unanswerable proven absent) | same | same |
| Documents | 4 real files from Drive: academic calendar PDF, handbook PDF, courses XLSX, website FAQ | same | same |
| Run | `eval-20261124-134100-7304c1` | same run (and again in the run of section 6) | `eval-20261125-045830-a4ce98` |

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
- **Model 3 / ablation:** measured on 2026-11-25; see section 6.

## 5. Validity

- Models 1 and 2 use the same model ID. The golden set is small (38); report counts, not just percentages. Settings were tuned on this same set, so the 93% is optimistic for unseen questions; a held-out set is the next honest step.
- Results are tied to the run date, the model ID and the four documents in Drive at that time.

## 6. Model 3 and the base-model ablation (measured once, 2026-11-25, run `eval-20261125-045830-a4ce98`)

Same 38 questions, same four documents (an index of 2,253 chunks), same retrieval settings and prompt version (`rag-v2`) in all three columns; a clean tree (commit `59fd015`); no errors in any mode.
The three modes received identical retrieved passages for every question (checked in the stored results), so the columns differ only in the model that wrote the answer. **Model 3** is `Qwen/Qwen3-4B-Instruct-2507` with the trained LoRA adapter on a vLLM endpoint (Modal).
The **ablation** is the same endpoint, the same base weights and the same sampling settings with the adapter switched off, so the only difference between those two columns is the adapter. Before the run, `scripts/check_model3_endpoint.py` confirmed that the endpoint lists the adapter next to the configured base model.

| Metric | Model 2 (hosted `gpt-6-luna`) | **Model 3** (base + adapter) | Ablation (same base, no adapter) |
|---|---:|---:|---:|
| Answer accuracy (of 30 answerable) | 28 = 93.3% | **24 = 80.0%** | 28 = 93.3% |
| False refusals (of 30) | 2 | 3 | 2 |
| Correct refusals (of 8 unanswerable) | 8 | 8 | 8 |
| Unsupported answers to the unanswerable | 0 | 0 | 0 |
| Citation hit (of 30) | 28 = 93.3% | 22 = 73.3% | 27 = 90.0% |
| Citation numbers valid | 100% | 100% | 100% |
| Proving quote reached the model | 100% | 100% | 100% |
| Latency p50 / p95 | 1.44 s / 2.14 s | 1.56 s / 2.64 s | 1.50 s / 3.29 s |
| Tokens in / out (total over 38) | 50,367 / 984 | 56,910 / 979 | 56,910 / 1,767 |
| Cost | $0.0055 | not priced (the endpoint bills GPU seconds, not tokens) | not priced |
| Mean words per answer | 15.2 | 13.7 | 29.2 |
| Mean citation marks per answer | 1.25 | 1.00 | 2.43 |

By category (correct / answerable): calendar 11/11, **7/11**, 11/11; handbook 10/10 in all three; FAQ 6/6 in all three; courses 1/3 in all three. Model 2 scored 28/30 here as in section 2 (the accepted baseline run scored 27/30).
The last two rows are counted from the answer text in `results.csv`, over the answerable questions each model answered rather than refused (28, 27 and 28 questions).

**What differed.** Model 3 and the ablation disagree on four questions, all calendar dates: the ablation was scored right and Model 3 wrong on each, and there is no question the other way round. Model 3 also fails the two spreadsheet fee questions (g29, g30) that Model 2 and the ablation fail. The four:

| Question | Model 3 answered | Expected (golden set) |
|---|---|---|
| g03 When do the Christmas vacations begin? | "September 23, 2026 [2]": a wrong month, citing the handbook page | 23 December |
| g05 When do the end semester examinations for odd semester UG programmes finish in October 2026? | refused ("I could not find this ..."), although the passages that prove the answer were in its context | 17 October |
| g06 When is the convocation at the Bangalore Central Campus? | "May 29-31, 2026 [1]": one of the two convocations in the passages (Model 2 and the ablation gave both) | 27-29 May (2027) |
| g09 When are the Session-I admission interviews held? | "September 11-13, 2026 [3]": one of the two sessions in the passages (Model 2 gave both) | 11-13 December |

**Reading it honestly**

- **On this set the adapter did not help: it scored lower.** 24 against 28 is four questions. When two models are equally good, a 4-0 split in the questions they disagree on happens about one time in eight (exact two-sided sign test, p = 0.125), so this is a hint, not a finding.
  Model 3 was run once. It and the ablation sample at temperature 0.2 (the default; the run's frozen configuration does not record it), while Models 1 and 2 send no temperature, so Model 3's run-to-run variation is unmeasured; for Model 2 it was about one question.
- **The ablation, not Model 2, is the fair comparison for the adapter.** Model 2 is a different and much larger hosted model; the ablation differs from Model 3 only by the adapter (and by sampling noise, which one run cannot separate from the adapter's effect).
- **The ablation's pass on g09 is lenient.** It also named only September ("September 2026 from 11 to 13"); it was scored correct because the accepted wordings for that question include "11 to 13" without a month. Counted strictly, the ablation scores 27/30 and the gap is three questions, not four.
  The same checker scores every mode, so the comparison is consistent, but I did not audit the other passes for the same blind spot.
- **What the adapter did change is the style it was trained on.** Its answers are about half the length of the ablation's (13.7 against 29.2 words) with one citation instead of two or three (1.00 against 2.43), close to Model 2's (15.2 words, 1.25), whose model wrote the training answers. That is the "behaviour, not facts" aim of ADR-023.
  A one-citation answer also picks one entry where the passages list two (g06, g09), and two correct answers (g01, g04) cited a different document from the expected one, which counts as a miss in citation hit; with three of the lost questions (g03, g05, g06) this accounts for the fall in citation hit from 90.0% to 73.3%.
- **No safety gain was measurable.** The ablation already refused all 8 unanswerable questions, invented nothing and cited valid passage numbers 100% of the time, so there was nothing for the adapter to improve there.
- **Cause not diagnosed; nothing tuned.** I did not investigate why the adapter said "September" for a December date, I did not retrain it, and I did not change a prompt or a setting or repeat the run after seeing the result (ADR-025): the golden set had already tuned the retrieval settings, so adjusting against it again would make the figure less trustworthy.
- **What this does not show.** It does not show that fine-tuning cannot help here: this is one adapter (344 training examples, 2 epochs, one training run, a validation set of 27) on one 38-question set. The adapter was trained without the passages that prove the golden answers and was not tuned on the set; the retrieval settings all three modes share were.
  A held-out question set and repeated runs are what a fair second attempt would need.
