"""Check the Model 3 endpoint (vLLM with the LoRA adapter) before anyone claims "Model 3 is PEFT".

  python scripts/check_model3_endpoint.py --wait 900     # a cold endpoint answers 503 for minutes: keep trying (every 10 s) until it is up, then check
  python scripts/check_model3_endpoint.py                # one attempt: what does the endpoint serve? is the adapter a LoRA of the configured base model?
  python scripts/check_model3_endpoint.py --ask          # also send one tiny question to the adapter and one to the base model (a fraction of a cent)
  python scripts/check_model3_endpoint.py --manifest data/peft/adapter_manifest.json   # also validate the adapter's manifest against the dataset and the app

Reads MODEL3_BASE_URL, MODEL3_API_KEY, MODEL3_MODEL, MODEL3_BASE_MODEL_ID and MODEL3_ADAPTER_ID from .env. The key is only sent to that endpoint.
Exit codes: 0 everything confirmed; 1 a problem was found; 2 Model 3 is not configured, the key was rejected, or the endpoint did not answer in time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.domain.model_modes import PROMPT_VERSIONS, ModelMode  # noqa: E402
from app.eval.adapter_manifest import (  # noqa: E402
    EndpointNotReady,
    RetryableError,
    check_models_payload,
    validate_manifest,
    wait_for_endpoint,
)


class KeyRejected(Exception):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ask", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--wait", type=float, default=0.0, help="keep trying for this many seconds while the endpoint starts (0 = one attempt)")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for each answer once the endpoint is up")
    args = parser.parse_args()

    s = get_settings()
    missing = [name for name, value in (("MODEL3_BASE_URL", s.model3_base_url), ("MODEL3_MODEL", s.model3_model),
                                        ("MODEL3_BASE_MODEL_ID", s.model3_base_model_id), ("MODEL3_ADAPTER_ID", s.model3_adapter_id)) if not value]
    if missing:
        print(f"Model 3 is not configured: set {', '.join(missing)} in .env (see docs/PEFT_TRAINING_AND_DEPLOYMENT.md).", file=sys.stderr)
        return 2
    base_url = s.model3_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {s.model3_api_key.get_secret_value()}"} if s.model3_api_key else {}
    try:
        import truststore

        truststore.inject_into_ssl()  # trust the operating system's certificates (antivirus / corporate HTTPS inspection)
    except ImportError:
        pass

    def fetch() -> dict:
        try:
            response = httpx.get(f"{base_url}/models", headers=headers, timeout=30.0)
        except httpx.TransportError as exc:  # refused, reset or timed out: the container is still starting
            raise RetryableError(type(exc).__name__) from exc
        if response.status_code in (502, 503, 504):  # a Modal Server answers 503 while a container starts
            raise RetryableError(f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
            raise KeyRejected(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    def say_waiting(attempt: int, remaining: float) -> None:
        print(f"  not up yet (attempt {attempt}); still waiting up to {int(remaining)} s ...", flush=True)

    problems: list[str] = []
    try:
        payload = wait_for_endpoint(fetch, args.wait, on_wait=say_waiting)
    except EndpointNotReady as exc:
        print(f"The endpoint did not answer at {base_url}/models ({exc}). A cold start can take several minutes the first time: run again with --wait 900.", file=sys.stderr)
        return 2
    except KeyRejected as exc:
        print(f"The endpoint rejected the key ({exc}). MODEL3_API_KEY in .env must equal the VLLM_API_KEY stored in the Modal secret.", file=sys.stderr)
        return 2
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Could not read {base_url}/models ({type(exc).__name__}).", file=sys.stderr)
        return 2
    found, notes = check_models_payload(payload, s.model3_model, s.model3_base_model_id, s.model3_adapter_id)
    problems += found
    print("served models:", ", ".join(str(m.get("id")) for m in payload.get("data", [])))
    for note in notes:
        print("  note:", note)

    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        dataset_path = REPO_ROOT / "data" / "peft" / "dataset_manifest.json"
        dataset = json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.is_file() else None
        errors, warnings = validate_manifest(manifest, current_prompt_version=PROMPT_VERSIONS[ModelMode.RAG_PEFT], dataset_manifest=dataset,
                                             configured_base_model=s.model3_base_model_id)
        problems += [f"manifest: {e}" for e in errors]
        for w in warnings:
            print("  warning:", w)

    if args.ask:
        for label, model in (("adapter", s.model3_model), ("base   ", s.model3_ablation_model or s.model3_base_model_id)):
            try:
                r = httpx.post(f"{base_url}/chat/completions", headers=headers, timeout=args.timeout,
                               json={"model": model, "max_tokens": 40, "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
                r.raise_for_status()
                print(f"  {label} ({model}) answered: {r.json()['choices'][0]['message']['content'].strip()[:60]!r}")
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                problems.append(f"{label} '{model}' did not answer a chat request ({type(exc).__name__})")

    if problems:
        print("PROBLEMS:\n  - " + "\n  - ".join(problems))
        return 1
    print("OK: the endpoint serves the adapter as a LoRA of the configured base model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
