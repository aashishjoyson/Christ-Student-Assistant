# Technical references and version checks

Checked on **20 November 2026** while producing this base repository. Re-check anything marked "verify"
before relying on it, and add a row whenever a phase adopts a new API.

## Versions and status found

| Component | Finding (2026-11-20) | Used as |
|---|---|---|
| LangGraph | 1.2.x current (1.2.14, 6 Oct 2026); 1.0 is an LTS line until 2.0 | `langgraph>=1.2,<2`; `StateGraph`, `START/END`, `add_conditional_edges`, `InMemorySaver` |
| FastAPI | 0.162.x current (13 Nov 2026) | `fastapi>=0.160,<1.0` |
| OpenAI Python SDK | 3.x current (3.41.0, 28 Oct 2026). 3.0.0 (Aug 2026) switched to HTTPX2 and stopped installing `httpx` | `openai>=3.0,<4`; `httpx` added to dev deps for TestClient |
| OpenAI models | **Verified 2026-11-23** on the official models + deprecations pages: model ID `gpt-6-luna` exists ("most efficient model for focused, high-volume tasks", $0.10 in / $0.50 out per 1M tokens, 1.05M context, 128K max output). It is the listed replacement for `gpt-5-nano`; `gpt-5-mini` maps to `gpt-6.1-terra`. `gpt-5`, `gpt-5-mini`, `gpt-5-nano` shut down **11 Dec 2026** (notice 11 Jun 2026); `gpt-4o-mini` / `gpt-4.1-mini` snapshots 14 Jan 2027. The Luna model page lists Chat Completions, Responses and Batch as supported. | `OPENAI_CHAT_MODEL=gpt-6-luna` (confirmed) |
| Reasoning-model parameters | Luna is a **reasoning model**: `reasoning.effort` supports `none, low, medium (default), high, xhigh, max`. On Chat Completions the field is `reasoning_effort` (values are model-dependent) and `max_completion_tokens` caps visible **plus reasoning** tokens, so a small cap at `medium` effort can return an empty answer (`empty_completion`). OpenAI's reasoning guide suggests reserving >= 25,000 tokens when experimenting. The pages read do **not** say how `temperature` behaves for Luna, so keep `LLM_TEMPERATURE` unset (the client only sends it when set). Note: the Chat Completions reference text was only available as a model-written summary, not verbatim. | optional params sent only when configured; recommended `.env` values in BUILD_REPORT.md |
| Installed in Phase 1 (2026-11-23) | Python 3.12.10, Node 24.13.0 / npm 11.6.2; FastAPI 0.165.0, LangGraph 1.2.24, openai 3.57.0, pydantic 2.14.4, chromadb 1.5.9, uvicorn 0.54.0, pytest 9.2.0, ruff 0.17.6, Vite 7.3.8 | exact pins in `backend/requirements.lock` and `frontend/package-lock.json` |
| Evidently | **Docs, PyPI metadata and a throwaway-venv spike (2026-11-24); not installed in `backend/.venv`.** PyPI latest 0.7.23, Apache-2.0, Python >= 3.10 (the docs changelog page is stale at 0.7.11). Core deps include scikit-learn, scipy, statsmodels, nltk, plotly<6, litestar, cryptography; the `[llm]` extra adds `torch`/`transformers`/`litellm`/`faiss`/`llama-index`. API (0.7): `from evidently import Dataset, DataDefinition, Report`; `from evidently.presets import TextEvals`; `from evidently.tests import eq, gte, lte`; `Report([...]).run(current, reference)`; `.dict()/.json()/.save_html()`. Descriptors: rule-based (`TextLength`, `Contains`, `IncludesWords`, `RegExp`), custom (`CustomColumnDescriptor`), HF-model (`HuggingFaceToxicity`, `SemanticSimilarity`), LLM-judged (`ToxicityLLMEval`, `DeclineLLMEval`, `FaithfulnessLLMEval`, `ContextQualityLLMEval`, `CompletenessLLMEval`, `CorrectnessLLMEval`, `LLMEval` + `BinaryClassificationPromptTemplate`; default `gpt-4o-mini`, OpenAI key, via LiteLLM). Adversarial-data generation is Cloud-only. **Spike findings:** needs `pandas<3` (pandas 3 breaks `import evidently`); `GroupBy(metric, column)` gives per-slice metrics and tests; pass/fail is `snapshot.dict()["tests"][i]["status"]` with `test_config.is_critical`; no library synthetic-data API in 0.7.23 (adversarial generation is Cloud-only); 4 unused compiled modules blocked by Windows Application Control; `litellm` resolves next to `openai` 3.x. | Phase 7.0 spike decides; see ADR-014 |
| SQLAlchemy | 2.1.9 resolves by default, but on the dev machine **Windows Application Control blocked its compiled extensions** (`ImportError: DLL load failed ... An Application Control policy has blocked this file`), so nothing importing SQLAlchemy could run. **2.0.58** (inside the declared `>=2.0.36,<2.2` range) imports and passes all tests; its own `cyextension` is also blocked but 2.0 falls back to pure Python automatically. The policy was not changed. | `requirements.lock` pins `SQLAlchemy==2.0.58`; `requirements.txt` range left unchanged |
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
- Evidently home / repo: https://www.evidentlyai.com/ , https://github.com/evidentlyai/evidently
- Evidently docs index (machine-readable): https://docs.evidentlyai.com/llms.txt ; LLM quickstart `quickstart_llm.md`; descriptors `metrics/all_descriptors.md`; custom judges `metrics/customize_llm_judge.md`; tests `docs/library/tests.md`; RAG example `examples/LLM_rag_evals.md`; regression testing `examples/LLM_regression_testing`; CI example `examples/GitHub_actions.md`; migration `faq/migration.md`
- Claude Code skills: https://code.claude.com/docs/en/skills
- Claude Code permissions: https://code.claude.com/docs/en/permissions

## Re-check log

| Date | Phase | What was re-checked | Change made |
|---|---|---|---|
| 2026-11-20 | 0 | All rows above | Initial versions and defaults |
| 2026-11-24 | 2 | chromadb 1.5.9 `PersistentClient(settings=Settings(anonymized_telemetry=False))` with collection metadata `hnsw:space=cosine` + `embedding_model`; pypdf 6.21.4; python-docx 1.2.0; openpyxl 3.1.5; `text-embedding-3-small` ($0.02 per 1M tokens, 100 inputs per request) | All worked on Windows with the real documents; telemetry disabled; spreadsheets get a per-row prefix; placeholders excluded by default |
| 2026-11-24 | 7.5 (M3) | GitHub REST API `releases/latest` for `actions/checkout`, `setup-python`, `setup-node`, `upload-artifact`; public `actions/runs` and `runs/{id}/jobs` endpoints | All four are at **v7** (checkout 7.0.1, setup-python 7.1.0, setup-node 7.1.0, upload-artifact 7.0.2); workflows pin v7. CI passed on the first run, so the v7 inputs used (`python-version`, `cache`, `node-version`, `cache-dependency-path`) are valid |
| 2026-11-24 | 3 (M1) | Google Drive API v3 docs: `files.list` (`q` = `'<id>' in parents and trashed = false`, `pageSize` up to 1000, `nextPageToken`, partial `fields`), `files.get(alt=media)`, `files.export` (Docs -> DOCX, Sheets -> XLSX; export limited to 10 MB), `md5Checksum` only for binary files (Google-native files use `version` + `modifiedTime`), scope `drive.readonly`, `execute(num_retries=5)` exponential backoff for 429/5xx; `truststore` for the Windows certificate store | Live listing against the user's folder connected (key, API enablement and sharing all correct; folder was empty at the time); everything else is covered by a fake Drive client that raises real `HttpError` objects. First live download/export is still to be shown. `truststore` added to `requirements.txt` |
| 2026-11-24 | 7.0 (spike) | Installed `evidently==0.7.23` in a throwaway venv; ran offline example, tests/pass-fail, `GroupBy`, Parquet, extension scan, `litellm`+`openai` 3.x resolver dry run | Go. `backend/requirements-eval.txt` pins `pandas<3`; Plan 7.0 ticked; docs corrected (slicing and CI status are available) |
| 2026-11-24 | 7 (planning) | Evidently GitHub README, docs.evidentlyai.com pages (LLM quickstart, descriptors, custom judges, tests, RAG, regression, CI, adversarial, migration), PyPI version and wheel metadata | Added Phase 7.0-7.7, FR-12, ADR-014; nothing installed; spike pending |
| 2026-11-23 | 1 | OpenAI models + deprecations pages (developers.openai.com/api/docs/models, /models/gpt-6-luna, /deprecations, /guides/reasoning) and Chat Completions reference; installed package versions | `gpt-6-luna` confirmed; recommended `LLM_REASONING_EFFORT=low` and `LLM_MAX_OUTPUT_TOKENS=4000` (not yet proven against the live API); SQLAlchemy pinned to 2.0.58 in `requirements.lock` because of the Application Control block; `tzdata` declared for Windows |
