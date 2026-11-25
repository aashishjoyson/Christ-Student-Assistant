"""The Colab notebook cannot be run here (no GPU), but what can be checked is checked: it parses, and the one function that must agree with the
app, the dataset hash that ties an adapter to its training data, gives the same value as app.eval.peft_data."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from app.core.config import REPO_ROOT
from app.eval.peft_data import dataset_sha256

NOTEBOOK = REPO_ROOT / "notebooks" / "train_lora_colab.ipynb"


def cells() -> list[dict]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def test_the_notebook_is_valid_and_every_code_cell_parses() -> None:
    data = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert data["nbformat"] == 4
    code = ["".join(c["source"]) for c in cells() if c["cell_type"] == "code"]
    assert len(code) >= 8
    for source in code:
        ast.parse("\n".join(line for line in source.splitlines() if not line.startswith("%")))  # IPython magics are not Python


def test_the_notebook_says_it_has_not_been_run_and_pins_its_packages() -> None:
    text = "".join("".join(c["source"]) for c in cells())
    assert "NOT been executed" in text
    for pin in ("trl==", "peft==", "transformers==", "bitsandbytes==", "accelerate==", "datasets=="):
        assert pin in text
    assert "private=True" in text  # the adapter goes to a private repository


def test_the_notebook_explains_the_expected_pip_warning_and_checks_4_bit_before_the_download() -> None:
    """Found on a real Colab run: installing datasets 5.2 (which needs pyarrow 24 or newer) makes pip warn that Colab's cuDF wants pyarrow below 24. The warning
    is harmless but pyarrow was already loaded, so the session must be restarted; and bitsandbytes must be proven on this GPU before the large download."""
    sources = ["".join(c["source"]) for c in cells() if c["cell_type"] == "code"]
    install = next(s for s in sources if "%pip" in s)
    assert "cudf-cu13" in install and "Restart session" in install and "Disconnect and delete runtime" in install
    gpu_check = next(s for s in sources if "is_bf16_supported" in s)
    assert "bnb.nn.Linear4bit" in gpu_check
    first_download = min(i for i, s in enumerate(sources) if "from_pretrained" in s)
    assert sources.index(gpu_check) < first_download  # the check comes before the model is downloaded


def test_the_training_arguments_use_the_names_the_current_libraries_document() -> None:
    """Checked against the Transformers 5.24 and TRL 1.18 documentation on 2026-11-24: warmup_ratio is no longer a TrainingArguments parameter (a float
    warmup_steps below 1 is the ratio), TRL calls the length max_length, evaluation_strategy became eval_strategy, and from_pretrained takes dtype."""
    text = "".join("".join(c["source"]) for c in cells())
    assert "warmup_ratio=" not in text and "warmup_steps=0.03" in text
    assert "max_length=" in text and "max_seq_length" not in text
    assert "eval_strategy=" in text and "evaluation_strategy" not in text
    assert "dtype=COMPUTE_DTYPE" in text and "torch_dtype=" not in text
    assert "fp16=not BF16" in text and "assistant_only_loss=" in text  # a T4 has no bfloat16; the default would be bf16


def test_the_notebooks_dataset_hash_matches_the_apps(tmp_path: Path) -> None:
    source = next("".join(c["source"]) for c in cells() if c["cell_type"] == "code" and "def dataset_sha256(path):" in "".join(c["source"]))
    function = source[source.index("def dataset_sha256(path):"): source.index("dataset_manifest = ")]
    namespace: dict = {"hashlib": hashlib, "json": json}
    exec(function, namespace)  # noqa: S102 - the notebook's own function, executed on test data
    examples = [{"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "Fee: ₹2,60,000?"}, {"role": "assistant", "content": "Yes [1]."}]},
                {"messages": [{"role": "user", "content": "ü"}, {"role": "assistant", "content": "ok"}]}]
    path = tmp_path / "train.jsonl"
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in examples) + "\n", encoding="utf-8")
    assert namespace["dataset_sha256"](str(path)) == dataset_sha256(examples)
