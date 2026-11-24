"""Serve the Model 3 LoRA adapter on Modal with vLLM, behind an OpenAI-compatible API (UNTESTED DRAFT).

Written on 2026-11-24 from the Modal "vllm_inference" example and the vLLM LoRA documentation. It has NOT been deployed: there is no Modal account
or GPU where it was written. The first `modal deploy` is the real test; read its output. Things most likely to need a small fix are marked CHECK.

Setup, once:
  pip install modal==1.6.4 && modal setup
  modal secret create cu-helpdesk-vllm HF_TOKEN=<a read token for the PRIVATE adapter repo> VLLM_API_KEY=<a long random string you invent>
Edit the three CHANGE-ME values below from adapter_manifest.json / the notebook's last cell, then:
  modal deploy deploy/modal_vllm.py
and put the printed URL into .env:
  MODEL3_BASE_URL=<url>/v1   MODEL3_API_KEY=<the same VLLM_API_KEY>   MODEL3_MODEL=cu-helpdesk-lora
  MODEL3_BASE_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507   MODEL3_ADAPTER_ID=<repo>@<adapter commit>   MODEL3_ABLATION_MODEL=Qwen/Qwen3-4B-Instruct-2507
Then check it, and only then call it Model 3:  python scripts/check_model3_endpoint.py --ask --manifest data/peft/adapter_manifest.json

Cost: the container scales to zero after SCALEDOWN minutes idle; the first request after that waits for a cold start (tens of seconds to minutes: the
backend allows 90 s, so warm it before a demo or an evaluation). Billing is per second while a container is up.
"""

from __future__ import annotations

import json
import os
import subprocess

import modal

# ---- CHANGE-ME: copy these from adapter_manifest.json and the notebook's last cell (all three must be real values) ----
BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
BASE_REVISION = "CHANGE-ME-40-character-commit-of-the-base-model"
ADAPTER_REPO = "CHANGE-ME-hf-username/cu-helpdesk-lora"
ADAPTER_REVISION = "CHANGE-ME-40-character-commit-of-the-adapter"
# ------------------------------------------------------------------------------------------------------------------------

ADAPTER_NAME = "cu-helpdesk-lora"  # what MODEL3_MODEL must be set to
MAX_LORA_RANK = 16  # must be at least the adapter's rank (r in the manifest)
MAX_MODEL_LEN = 4096
PORT = 8000
SCALEDOWN = 5 * 60  # seconds idle before the container stops
VLLM_VERSION = "0.34.0"  # latest on PyPI on 2026-11-24; the Modal example pins an older one, so CHECK the first start-up log

PLACEHOLDERS = [name for name, value in (("BASE_REVISION", BASE_REVISION), ("ADAPTER_REPO", ADAPTER_REPO), ("ADAPTER_REVISION", ADAPTER_REVISION))
                if value.startswith("CHANGE-ME")]
if PLACEHOLDERS and os.environ.get("MODAL_IS_REMOTE") != "1":
    raise SystemExit(f"Edit deploy/modal_vllm.py first: {', '.join(PLACEHOLDERS)} still hold the CHANGE-ME placeholder.")

app = modal.App("cu-helpdesk-model3")

image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub==2.4.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "MODAL_IS_REMOTE": "1"})
)
hf_cache = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)
secrets = modal.Secret.from_name("cu-helpdesk-vllm")  # HF_TOKEN, VLLM_API_KEY


@app.server(  # CHECK: this decorator and its arguments follow the Modal vllm_inference example of 2026-11-24
    image=image,
    gpu="L4",  # CHECK: 24 GB is enough for a 4B model in 16-bit plus the adapter and a 4k context; use "A10G" if L4 is unavailable
    scaledown_window=SCALEDOWN,
    startup_timeout=15 * 60,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
    secrets=[secrets],  # CHECK: the example does not use secrets; if app.server rejects this argument, set the key with image.env() instead
    port=PORT,
    target_concurrency=8,
    unauthenticated=True,  # Modal's own proxy auth is off; vLLM enforces the API key (--api-key) itself
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
