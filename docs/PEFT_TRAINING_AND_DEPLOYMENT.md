# PEFT (LoRA) training and Model 3 deployment (Phase 6)

## Status (2026-11-24): the tooling is built; training and deployment need your accounts

| Step | State | File |
|---|---|---|
| 1. Build the training set | **Done**: 371 examples (284 answerable, 87 refusals), train 344 / val 27, about $0.03 | `scripts/build_peft_dataset.py`, `data/peft/dataset_manifest.json` |
| 2. Train the adapter (Colab T4, QLoRA) | **Written from the TRL/PEFT docs, not run** (no GPU here) | `notebooks/train_lora_colab.ipynb` |
| 3. Serve it (Modal + vLLM) | **Written from the Modal/vLLM docs, not deployed** | `deploy/modal_vllm.py` |
| 4. Prove it is a LoRA of the base model | Built and tested with fakes | `scripts/check_model3_endpoint.py --ask --manifest data/peft/adapter_manifest.json` |
| 5. Measure it against its base and Model 2 | Built (`rag_peft`, `rag_peft_base` modes) | `python scripts/run_evaluation.py --modes rag,rag_peft,rag_peft_base` |
| 6. Promote through the same gates | Built | `python scripts/compare_eval.py latest --mode rag_peft` |

**What you do** (about an hour of clicking, plus Colab time): create a Hugging Face account and a write token; open the notebook in Colab with a T4; upload `data/peft/train.jsonl`, `val.jsonl` and `dataset_manifest.json`; run it; create a Modal account, run the two
`modal secret` and `modal deploy` commands in `deploy/modal_vllm.py`; put the printed values in `.env`; run the checker; run the evaluation. Nothing in this repository can do those steps for you, and none of them has been run.

**Differences from the plan below, and why:** the training set is built from the **real documents in the index** (the plan said synthetic documents; the adapter teaches behaviour, not facts, and the repository holds no weights), with a hosted model as the teacher; there are **no scope/safety
examples** because change requests are handled by routing rules and never reach the model; passages that prove any golden-set answer are **held out completely** and questions close to golden questions are dropped, so Model 3 can be evaluated fairly on the same golden set; the validation
split is small (27) because the set is small, so treat `eval_loss` as a rough signal only. Package versions looked up on 2026-11-24: vLLM 0.34.0, TRL 1.18.2, PEFT 0.22.0, Transformers 5.24.0, bitsandbytes 0.50.2, Modal 1.6.4.

## What the adapter is for

The adapter teaches **behaviour**, not facts: answer only from the numbered passages, cite them as `[n]`,
use the exact refusal sentence when the passages lack the answer, stay in scope, keep answers short. University
facts stay in RAG so they can change without retraining. This is what makes Model 3 measurable against Model 2
(citation format adherence and refusal correctness).

## Base model

`Qwen/Qwen3-4B-Instruct-2507` - Apache-2.0, ungated, non-thinking instruct variant (no `<think>` blocks to manage),
supported by Transformers, PEFT and vLLM. Re-check the model card (licence, revision) before training and record
the exact revision hash in the manifest. Fallback if Colab memory is tight: `Qwen/Qwen3-1.7B` (hybrid thinking
model - disable thinking in the chat template during both training and serving).

## Dataset (`scripts/build_peft_dataset.py`)

- Built from `data/sample_docs` (synthetic) using the app's own `build_rag_messages()` so train and serve formats match.
- ~400-800 examples: ~60% answerable (2-4 passages, answer cites the right `[n]`), ~25% unanswerable (distractor
  passages, exact refusal sentence), ~15% scope/safety (requests to change grades, etc. -> polite scope reply).
- Remove any question that appears in `data/eval/*` (prevents train/test leakage).
- No applicant data, no real university documents unless you have permission.
- Save `train.jsonl`/`val.jsonl` with `{"messages": [...]}` and a dataset hash for the manifest.

## Training on Colab (T4 16 GB)

| Setting | Value |
|---|---|
| Quantisation | 4-bit NF4 (bitsandbytes), double quant |
| Precision | fp16 (T4 has no bf16) |
| LoRA | r=16, alpha=32, dropout=0.05, targets q,k,v,o,gate,up,down proj |
| Sequence length | 2048 |
| Batch | 1-2 with gradient accumulation to an effective 16 |
| Epochs / LR | 2 / 2e-4, cosine, warmup 3% |
| Trainer | TRL `SFTTrainer` (assistant-only loss if available) |

Outputs: `adapter_model.safetensors`, `adapter_config.json`, tokenizer files, and `adapter_manifest.json`:
```json
{"base_model_id": "Qwen/Qwen3-4B-Instruct-2507", "base_model_revision": "<commit>", "dataset_sha256": "<hash>",
 "lora": {"r": 16, "alpha": 32, "dropout": 0.05}, "epochs": 2, "trained_at": "<date>", "prompt_version": "rag-v1"}
```
Push to a **private** Hugging Face repo; note the commit hash. Never commit weights to Git.

## Serving: vLLM with LoRA on Modal (recommended)

Why: vLLM serves the base model and named adapters through an OpenAI-compatible API, so the backend needs no new
code; Modal bills per second and scales to zero, and the Starter plan includes monthly credit.

Shape of `deploy/modal_vllm.py` (Phase 6 writes and tests it):
```text
image: vllm (pinned) + huggingface_hub
secrets: HF_TOKEN (read private adapter), VLLM_API_KEY
gpu: L4 or A10G (24 GB) - 4B model in bf16/fp16 fits with room for KV cache
command: vllm serve Qwen/Qwen3-4B-Instruct-2507 --revision <commit>
         --enable-lora --lora-modules cu-helpdesk-lora=<hf-user>/cu-helpdesk-lora
         --max-lora-rank 16 --max-model-len 4096 --api-key $VLLM_API_KEY
scaledown: a few minutes idle -> zero
```
Then set:
```dotenv
MODEL3_BASE_URL=https://<your-modal-app>.modal.run/v1
MODEL3_API_KEY=<VLLM_API_KEY>
MODEL3_MODEL=cu-helpdesk-lora
MODEL3_BASE_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
MODEL3_ADAPTER_ID=<hf-user>/cu-helpdesk-lora@<commit>
MODEL3_ABLATION_MODEL=Qwen/Qwen3-4B-Instruct-2507
```
Run `python scripts/check_model3_endpoint.py`: it must find `cu-helpdesk-lora` in `/v1/models` with parent
`Qwen/Qwen3-4B-Instruct-2507` before you claim Model 3 is PEFT.

**Cost control:** first request after idle takes tens of seconds (cold start; the backend timeout is 90 s). Warm the
endpoint before demos and evaluation; stop the app afterwards. A full evaluation run is typically well under one
GPU-hour - check current GPU prices on the provider page.

## Alternatives

| Option | Notes |
|---|---|
| HF Inference Endpoints (vLLM container) | Per-minute billing, scale-to-zero after 15 min; cold start returns 502 until ready |
| CoreWeave / W&B serverless LoRA | Per-token and no GPU management, but only a few base models are supported - you would have to train on one of them (check the current list) |
| Colab + tunnel | Free but ephemeral and fragile; not suitable as the "cloud endpoint" |

## Experimental note

Report Model 3 alongside the ablation (`MODEL3_ABLATION_MODEL`, same endpoint, no adapter). The difference
between "Model 3-base + RAG" and "Model 3 + RAG" is the PEFT effect; the difference between Model 2 and Model 3 also
includes the backbone difference.
