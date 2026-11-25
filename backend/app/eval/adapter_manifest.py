"""The adapter manifest and the endpoint check: what must be true before anyone may say "Model 3 is a LoRA of this base model, trained on this data" (stdlib only).

The manifest is written by the training notebook next to the adapter. Validating it ties three things together: the adapter to the exact data
it was trained on (hash), to the prompt format the app serves (version), and to the base model the endpoint loads (id and pinned commit).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

REQUIRED_FIELDS = ("base_model_id", "base_model_revision", "dataset_sha256", "lora", "epochs", "trained_at", "prompt_version")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RetryableError(Exception):
    """The endpoint is not ready yet (a cold start: Modal answers 503 until vLLM is up; a connection that is refused or times out). Worth trying again."""


class EndpointNotReady(Exception):
    """The endpoint still had not answered when the waiting time ran out."""


def wait_for_endpoint(
    fetch: Callable[[], Any], wait_seconds: float, interval: float = 10.0, clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep, on_wait: Callable[[int, float], None] | None = None,
) -> Any:
    """Call `fetch` until it succeeds. Only RetryableError is retried (any other error, such as a rejected key, is raised at once). With wait_seconds=0 it
    is a single attempt. Raises EndpointNotReady when the deadline passes. `clock` and `sleep` are injectable so the behaviour is tested without waiting."""
    deadline = clock() + wait_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            return fetch()
        except RetryableError as exc:
            remaining = deadline - clock()
            if remaining <= 0:
                raise EndpointNotReady(f"no answer after {attempt} attempt(s): {exc}") from exc
            if on_wait is not None:
                on_wait(attempt, remaining)
            sleep(min(interval, remaining))


def validate_manifest(manifest: dict[str, Any], *, current_prompt_version: str, dataset_manifest: dict[str, Any] | None = None,
                      configured_base_model: str | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors mean the adapter must not be called Model 3 yet."""
    errors: list[str] = []
    warnings: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"missing field '{field}'")
    if errors:
        return errors, warnings

    if not _COMMIT.match(str(manifest["base_model_revision"])):
        errors.append("base_model_revision must be the 40-character commit of the base model (a branch name or 'main' can change under you)")
    if not _SHA256.match(str(manifest["dataset_sha256"])):
        errors.append("dataset_sha256 must be a 64-character SHA-256 of the training file")
    lora = manifest["lora"]
    if not isinstance(lora, dict) or not all(isinstance(lora.get(k), (int, float)) for k in ("r", "alpha", "dropout")):
        errors.append("lora must give numeric r, alpha and dropout")
    if not isinstance(manifest["epochs"], (int, float)) or manifest["epochs"] <= 0:
        errors.append("epochs must be a positive number")
    try:
        datetime.fromisoformat(str(manifest["trained_at"]).replace("Z", "+00:00"))
    except ValueError:
        errors.append("trained_at must be an ISO date-time")
    if manifest["prompt_version"] != current_prompt_version:
        errors.append(f"the adapter was trained on prompt '{manifest['prompt_version']}' but the app serves '{current_prompt_version}': "
                      "it learned a format the app no longer sends. Retrain on the current prompt, or serve the matching app version.")
    if configured_base_model and manifest["base_model_id"] != configured_base_model:
        errors.append(f"the adapter's base is '{manifest['base_model_id']}' but MODEL3_BASE_MODEL_ID is '{configured_base_model}'")
    if dataset_manifest is not None and dataset_manifest.get("train_sha256") != manifest["dataset_sha256"]:
        errors.append("dataset_sha256 does not match data/peft/dataset_manifest.json: the adapter was not trained on this dataset")
    if "eval_loss" not in manifest:
        warnings.append("no eval_loss recorded: there is no evidence the adapter fits held-out examples")
    if "libraries" not in manifest:
        warnings.append("no library versions recorded: the training run cannot be reproduced exactly")
    if isinstance(lora, dict) and isinstance(lora.get("r"), (int, float)) and lora["r"] > 16:
        warnings.append(f"LoRA rank {lora['r']} is above 16: start vLLM with --max-lora-rank {int(lora['r'])} or it will refuse the adapter")
    return errors, warnings


def check_models_payload(payload: dict[str, Any], adapter_name: str, base_model_id: str, adapter_repo: str | None = None) -> tuple[list[str], list[str]]:
    """Check what a vLLM server lists at GET /v1/models. (problems, notes). No problems means it serves the adapter as a LoRA of the base model."""
    problems: list[str] = []
    notes: list[str] = []
    entries = {str(m.get("id")): m for m in payload.get("data", []) if isinstance(m, dict)}
    if not entries:
        return ["the endpoint lists no models"], notes
    if base_model_id not in entries:
        problems.append(f"the base model '{base_model_id}' is not served (found: {sorted(entries)})")
    adapter = entries.get(adapter_name)
    if adapter is None:
        problems.append(f"the adapter '{adapter_name}' is not served (found: {sorted(entries)}): check --lora-modules and --enable-lora")
        return problems, notes
    parent, root = adapter.get("parent"), str(adapter.get("root") or "")
    if parent == base_model_id:
        notes.append(f"'{adapter_name}' is reported as a LoRA of '{base_model_id}' (parent matches)")
    elif parent:
        problems.append(f"'{adapter_name}' has parent '{parent}', not the configured base '{base_model_id}'")
    elif adapter_repo and (adapter_repo.split("@")[0] in root or adapter_repo.split("@")[0].replace("/", "--") in root):  # a Hugging Face cache path says user--repo
        notes.append(f"'{adapter_name}' reports no parent, but its root points at the adapter artifact '{root}'. Use the JSON form of --lora-modules "
                     "with base_model_name so the server states the parent.")
    else:
        problems.append(f"'{adapter_name}' reports no parent and its root '{root}' does not identify the adapter: cannot confirm it is a LoRA of the base model")
    if adapter_name == base_model_id:
        problems.append("the adapter has the same name as the base model; the app would be unable to tell them apart")
    return problems, notes
