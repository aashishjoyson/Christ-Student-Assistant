"""deploy/modal_vllm.py cannot be deployed here (no Modal account, no GPU), so these tests guard what can be guarded: it parses, it refuses to deploy
with placeholders, and it passes vLLM the flags that make the adapter verifiable."""

from __future__ import annotations

import ast

from app.core.config import REPO_ROOT

SOURCE = (REPO_ROOT / "deploy" / "modal_vllm.py").read_text(encoding="utf-8")


def test_the_file_parses_and_says_it_is_an_untested_draft() -> None:
    ast.parse(SOURCE)
    assert "UNTESTED DRAFT" in SOURCE and "has NOT been deployed" in SOURCE


def test_it_will_not_deploy_while_the_placeholders_are_still_there() -> None:
    assert SOURCE.count('"CHANGE-ME') >= 3 and 'startswith("CHANGE-ME")' in SOURCE and "SystemExit" in SOURCE


def test_vllm_is_started_with_the_flags_the_endpoint_check_relies_on() -> None:
    for fragment in ('"--enable-lora"', '"--lora-modules"', '"--max-lora-rank"', '"--api-key"', '"--revision"', "base_model_name", "snapshot_download",
                     "revision=ADAPTER_REVISION", 'MODEL3_MODEL', "scaledown_window"):
        assert fragment in SOURCE, fragment


def test_no_secret_value_is_written_in_the_file() -> None:
    assert "hf_" not in SOURCE.replace("hf_cache", "").replace("hf_username", "").replace("HF_", "").replace("hf-", "")
    assert 'os.environ["HF_TOKEN"]' in SOURCE and 'os.environ["VLLM_API_KEY"]' in SOURCE
