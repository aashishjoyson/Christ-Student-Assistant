"""Serve the Model 3 LoRA adapter on Modal with vLLM, behind an OpenAI-compatible API.

STATUS: UNTESTED ON MODAL. Written on 2026-11-24 from the Modal Servers guide, the Modal vllm_inference example and the vLLM LoRA documentation, and checked on
2026-11-25 against the documented parameter list of `App.server` (it accepts image, secrets, gpu, volumes, port, scaledown_window, startup_timeout,
target_concurrency and unauthenticated). The logic below (configuration, the vLLM command, the adapter download) is exercised by tests/unit/test_modal_deploy_file.py
with a stand-in for `modal`; what only a real deployment can show is the Modal side. The first `modal deploy` is the real test: read its output.

Setup, once (a separate virtual environment is tidiest). Windows Application Control blocks the small launcher programs a new environment creates (pip.exe, modal.exe),
so on such a machine run everything as `python -m ...` (python itself is allowed):
  python -m pip install modal==1.6.4
  python -m modal setup                        # opens a browser to log in
  python -c "import secrets; print(secrets.token_urlsafe(32))"     # invent the key vLLM will require; keep it for .env
  python -m modal secret create cu-helpdesk-vllm HF_TOKEN=<read token for the PRIVATE adapter repo> VLLM_API_KEY=<the key above>

Billing (checked against Modal's docs on 2026-11-25): Modal requires a payment method on file before it will run any GPU (`modal deploy` stops with "Please add a payment method
to use L4 GPU functions" otherwise). The free Starter plan includes $30 of compute credit per month, and an L4 is listed at $0.000222 per second (about $0.80 per hour), so
this project's use fits inside the credit. To be certain you are never charged, open modal.com/settings/usage (Usage & Billing) and set the workspace SPEND LIMIT low
(it caps what you pay out of pocket after credits; Modal stops workloads that would exceed it). When you are done, stop the app from the dashboard (Apps > cu-helpdesk-model3).

Configuration (not secret, but personal, so it is not committed): the base-model commit, the adapter repository and the adapter commit come from either the environment
(MODEL3_BASE_REVISION, MODEL3_ADAPTER_REPO, MODEL3_ADAPTER_REVISION) or deploy/model3.local.json (git-ignored):
  {"base_model_revision": "<40 hex>", "adapter_repo": "<hf-user>/cu-helpdesk-lora", "adapter_revision": "<40 hex>"}

Deploy and connect:
  python -m modal deploy deploy/modal_vllm.py
  The URL is in the Modal dashboard (Apps > cu-helpdesk-model3) or:
    python -c "import modal; print(modal.Server.from_name('cu-helpdesk-model3', 'Server').get_url())"
  .env:  MODEL3_BASE_URL=<url>/v1   MODEL3_API_KEY=<the same key>   MODEL3_MODEL=cu-helpdesk-lora
         MODEL3_BASE_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507   MODEL3_ADAPTER_ID=<repo>@<adapter commit>   MODEL3_ABLATION_MODEL=Qwen/Qwen3-4B-Instruct-2507
  Then check it, and only then call it Model 3:
    python scripts/check_model3_endpoint.py --wait 900 --ask --manifest data/peft/adapter_manifest.json

COLD STARTS: a Modal Server does NOT queue requests while a container starts; it answers 503 until vLLM is up (the first time this includes downloading the 8 GB base model
into the cache volume, so allow several minutes; later starts are faster). The container stops after SCALEDOWN seconds idle. Warm it before a demo or an evaluation:
`--wait 900` above polls until it is ready. Model 3 in the app reports the endpoint error and never falls back to another model while it is cold. Billing is per second
while a container is up (an L4 was listed at about $0.80 per hour on 2026-11-25).

SECURITY: unauthenticated=True turns off Modal's own proxy login so the app can call the endpoint with only the vLLM key; vLLM then requires that key (--api-key) for
every /v1 request. The URL is public, so keep the key secret. /health stays open by design.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import modal

# ---- configuration: environment first, then the git-ignored local file; a placeholder stops the deployment ----
LOCAL_CONFIG = Path(os.environ.get("MODEL3_LOCAL_CONFIG") or Path(__file__).with_name("model3.local.json"))
_local: dict[str, str] = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8")) if LOCAL_CONFIG.is_file() else {}


def _setting(env_name: str, key: str) -> str:
    return os.environ.get(env_name) or str(_local.get(key) or f"CHANGE-ME ({key})")


BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
BASE_REVISION = _setting("MODEL3_BASE_REVISION", "base_model_revision")
ADAPTER_REPO = _setting("MODEL3_ADAPTER_REPO", "adapter_repo")
ADAPTER_REVISION = _setting("MODEL3_ADAPTER_REVISION", "adapter_revision")

ADAPTER_NAME = "cu-helpdesk-lora"  # what MODEL3_MODEL must be set to
MAX_LORA_RANK = 16  # must be at least the adapter's rank (r in the manifest)
MAX_MODEL_LEN = 4096
PORT = 8000
SCALEDOWN = 5 * 60  # seconds idle before the container stops
VLLM_VERSION = "0.34.0"  # latest on PyPI on 2026-11-24; the Modal example pins an older one, so read the first start-up log

PLACEHOLDERS = [name for name, value in (("MODEL3_BASE_REVISION / base_model_revision", BASE_REVISION), ("MODEL3_ADAPTER_REPO / adapter_repo", ADAPTER_REPO),
                                         ("MODEL3_ADAPTER_REVISION / adapter_revision", ADAPTER_REVISION)) if value.startswith("CHANGE-ME")]
if PLACEHOLDERS and os.environ.get("MODAL_IS_REMOTE") != "1":
    raise SystemExit("Missing configuration: " + "; ".join(PLACEHOLDERS) + ". Set the environment variables or create deploy/model3.local.json (see the top of this file).")

app = modal.App("cu-helpdesk-model3")

image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub==2.4.0")
    # The configuration is baked into the image environment so the running container has it (this file's local JSON is not uploaded). None of it is secret.
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "MODAL_IS_REMOTE": "1", "MODEL3_BASE_REVISION": BASE_REVISION, "MODEL3_ADAPTER_REPO": ADAPTER_REPO,
          "MODEL3_ADAPTER_REVISION": ADAPTER_REVISION})
)
hf_cache = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)
vllm_secret = modal.Secret.from_name("cu-helpdesk-vllm")  # HF_TOKEN, VLLM_API_KEY


@app.server(
    image=image,
    gpu="L4",  # 24 GB is enough for a 4B model in 16-bit plus the adapter and a 4k context; "A10" is the other 24 GB option (there is no "A10G" in Modal)
    scaledown_window=SCALEDOWN,
    startup_timeout=15 * 60,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
    secrets=[vllm_secret],
    port=PORT,
    target_concurrency=8,
    unauthenticated=True,  # see SECURITY above
)
class Server:
    @modal.enter()
    def start(self) -> None:
        from huggingface_hub import snapshot_download

        # The adapter is fetched at an exact commit, so the endpoint serves what the manifest describes and nothing newer.
        adapter_dir = snapshot_download(ADAPTER_REPO, revision=ADAPTER_REVISION, token=os.environ["HF_TOKEN"])
        # The JSON form states the base model, so GET /v1/models reports "parent" and scripts/check_model3_endpoint.py can confirm it is a LoRA.
        lora = json.dumps({"name": ADAPTER_NAME, "path": adapter_dir, "base_model_name": BASE_MODEL})
        command = [
            "vllm", "serve", BASE_MODEL, "--revision", BASE_REVISION,
            "--host", "0.0.0.0", "--port", str(PORT), "--api-key", os.environ["VLLM_API_KEY"],  # noqa: S104 - inside the container, behind the API key
            "--enable-lora", "--lora-modules", lora, "--max-lora-rank", str(MAX_LORA_RANK),
            "--max-model-len", str(MAX_MODEL_LEN),
        ]
        self.process = subprocess.Popen(command)  # noqa: S603 - fixed arguments; the secrets come from the Modal secret

    @modal.exit()
    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
