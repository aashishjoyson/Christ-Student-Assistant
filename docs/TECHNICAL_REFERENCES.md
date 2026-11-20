# Technical references and version checks

Checked on **20 November 2026** while producing this base repository. Re-check anything marked "verify"
before relying on it, and add a row whenever a phase adopts a new API.

## Versions and status found

| Component | Finding (2026-11-20) | Used as |
|---|---|---|
| LangGraph | 1.2.x current (1.2.14, 6 Oct 2026); 1.0 is an LTS line until 2.0 | `langgraph>=1.2,<2`; `StateGraph`, `START/END`, `add_conditional_edges`, `InMemorySaver` |
| FastAPI | 0.162.x current (13 Nov 2026) | `fastapi>=0.160,<1.0` |
| OpenAI Python SDK | 3.x current (3.41.0, 28 Oct 2026). 3.0.0 (Aug 2026) switched to HTTPX2 and stopped installing `httpx` | `openai>=3.0,<4`; `httpx` added to dev deps for TestClient |
| OpenAI models | `gpt-5`, `gpt-5-mini`, `gpt-5-nano` shut down 11 Dec 2026; `gpt-4o(-mini)` / `gpt-4.1(-mini)` snapshots 14 Jan 2027; GPT-6 Luna recommended for small-model replacements, listed around $0.10 / $0.50 per 1M tokens | default `OPENAI_CHAT_MODEL=gpt-6-luna` - **verify exact ID** |
| Reasoning-model parameters | GPT-5-family reasoning models reject `temperature`/`top_p`; use `max_completion_tokens`; `reasoning_effort` values vary by model | optional params sent only when configured |
| Embeddings | `text-embedding-3-small` | default `OPENAI_EMBEDDING_MODEL` - verify price/status |
| Chroma | 1.5.x (`PersistentClient(path=...)`) | `chromadb>=1.5,<2` |
| MLflow | Since 3.7 the default tracking backend is SQLite; file store is deprecated | optional, `sqlite:///storage/mlflow.db` |
| vLLM | 0.32.0 (Oct 2026); LoRA via `--enable-lora`, `--lora-modules name=path`, `--max-lora-rank` (default 16) | Model 3 serving |
| Serverless LoRA market | Together AI discontinued serverless LoRA (dedicated endpoints now); Fireworks serverless LoRA preview limited; CoreWeave/W&B serverless LoRA supports a short list of base models | Modal + vLLM recommended |
| Modal | Starter plan: $0 platform fee + $30/month compute credit; per-second GPU billing | recommended Model 3 host |
| HF Inference Endpoints | per-minute billing, optional scale-to-zero (15 min idle, cold start returns 502 until ready) | alternative Model 3 host |
| Base model | `Qwen/Qwen3-4B-Instruct-2507`: Apache-2.0, ungated, non-thinking instruct variant, ~4B params | PEFT base |
| Google OAuth | Apps in "Testing" status: authorizations and refresh tokens expire 7 days after consent | service account as default |
| Claude Code | Custom commands merged into skills (`.claude/skills/<name>/SKILL.md`; `.claude/commands/` still works); `settings.json` permission rules like `Bash(npm run *)`, `Read(./.env)` | repo skills + settings |

## Official documentation to consult per phase

- LangGraph overview / graph API: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph release policy: https://docs.langchain.com/oss/python/release-policy
- OpenAI Chat Completions reference: https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create
- OpenAI deprecations: https://developers.openai.com/api/docs/deprecations
- OpenAI pricing: https://developers.openai.com/api/docs/pricing
- OpenAI embeddings guide: https://developers.openai.com/api/docs/guides/embeddings
- Google Drive API v3 reference: https://developers.google.com/workspace/drive/api/reference/rest/v3
- Drive download/export guide: https://developers.google.com/workspace/drive/api/guides/manage-downloads
- Google OAuth consent / publishing status: https://support.google.com/cloud/answer/15549945
- Chroma docs: https://docs.trychroma.com
- Hugging Face PEFT quicktour: https://huggingface.co/docs/peft/quicktour
- Transformers PEFT integration: https://huggingface.co/docs/transformers/peft
- vLLM LoRA serving (0.32): https://docs.vllm.ai/en/v0.32.0/features/lora/
- Modal pricing: https://modal.com/pricing
- HF Inference Endpoints pricing: https://huggingface.co/docs/inference-endpoints/pricing
- MLflow self-hosting / backend store: https://mlflow.org/docs/latest/self-hosting/
- Claude Code skills: https://code.claude.com/docs/en/skills
- Claude Code permissions: https://code.claude.com/docs/en/permissions

## Re-check log

| Date | Phase | What was re-checked | Change made |
|---|---|---|---|
| 2026-11-20 | 0 | All rows above | Initial versions and defaults |
