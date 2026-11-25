"""deploy/modal_vllm.py cannot be deployed here (no Modal account, no GPU), but everything that is OUR logic can be run: the file is imported with a stand-in for `modal`,
so the configuration, the decorator arguments, the adapter download and the exact vLLM command are executed and checked."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from app.core.config import REPO_ROOT

FILE = REPO_ROOT / "deploy" / "modal_vllm.py"
SOURCE = FILE.read_text(encoding="utf-8")

# What Modal documents (SDK reference for App.server and the GPU guide, read on 2026-11-25). A typo in our arguments would only show at the first deploy.
SERVER_PARAMETERS = {
    "image", "env", "secrets", "gpu", "serialized", "volumes", "cpu", "memory", "ephemeral_disk", "target_concurrency", "max_concurrency", "min_containers",
    "max_containers", "buffer_containers", "scaleup_window", "scaledown_window", "startup_timeout", "name", "port", "unauthenticated", "h2_enabled",
    "exit_grace_period", "routing_region", "compute_region", "cloud", "nonpreemptible", "proxy", "i6pn", "enable_memory_snapshot", "include_source",
    "experimental_options",
}
GPU_NAMES = {"T4", "L4", "A10", "L40S", "A100", "A100-40GB", "A100-80GB", "RTX-PRO-6000", "H100", "H100!", "H200", "B200", "B200+", "B300"}
CONFIG = {"base_model_revision": "b" * 40, "adapter_repo": "someone/cu-helpdesk-lora", "adapter_revision": "a" * 40}


class Fluent:
    """Stands in for modal.Image / Volume / Secret: any chain of calls returns itself and is recorded."""

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Fluent:
            self.calls.append((name, args, kwargs))
            return self

        return call


def load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str] | None = None, local: dict[str, str] | None = None) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {"calls": []}
    fake = types.ModuleType("modal")

    class App:
        def __init__(self, name: str) -> None:
            captured["app_name"] = name

        def server(self, **kwargs: Any):  # type: ignore[no-untyped-def]
            captured["server"] = kwargs
            return lambda cls: cls

    fake.App = App  # type: ignore[attr-defined]
    fake.Image = fake.Volume = fake.Secret = Fluent(captured["calls"])  # type: ignore[attr-defined]
    fake.enter = fake.exit = lambda: (lambda function: function)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "modal", fake)
    for name in ("MODEL3_BASE_REVISION", "MODEL3_ADAPTER_REPO", "MODEL3_ADAPTER_REVISION", "MODAL_IS_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "model3.local.json"
    if local is not None:
        config.write_text(json.dumps(local), encoding="utf-8")
    monkeypatch.setenv("MODEL3_LOCAL_CONFIG", str(config))
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("modal_vllm_under_test", FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, captured


def test_the_file_parses_and_says_it_has_not_run_on_modal() -> None:
    ast.parse(SOURCE)
    assert "UNTESTED ON MODAL" in SOURCE and "COLD STARTS" in SOURCE and "503" in SOURCE


def test_it_refuses_to_deploy_without_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stop:
        load(monkeypatch, tmp_path)
    message = str(stop.value)
    assert "model3.local.json" in message and "base_model_revision" in message and "adapter_repo" in message and "adapter_revision" in message


def test_one_missing_value_is_named(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stop:
        load(monkeypatch, tmp_path, local={k: v for k, v in CONFIG.items() if k != "adapter_revision"})
    assert "adapter_revision" in str(stop.value) and "base_model_revision" not in str(stop.value)


def test_configuration_comes_from_the_local_file_and_the_environment_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load(monkeypatch, tmp_path, local=CONFIG)
    assert (CONFIG["base_model_revision"], CONFIG["adapter_repo"], CONFIG["adapter_revision"]) == (module.BASE_REVISION, module.ADAPTER_REPO, module.ADAPTER_REVISION)
    module, _ = load(monkeypatch, tmp_path, local=CONFIG, env={"MODEL3_ADAPTER_REVISION": "c" * 40})
    assert module.ADAPTER_REVISION == "c" * 40 and CONFIG["adapter_repo"] == module.ADAPTER_REPO


def test_the_server_is_declared_with_only_documented_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, captured = load(monkeypatch, tmp_path, local=CONFIG)
    server = captured["server"]
    assert captured["app_name"] == "cu-helpdesk-model3"
    assert set(server) <= SERVER_PARAMETERS, set(server) - SERVER_PARAMETERS
    gpus = server["gpu"] if isinstance(server["gpu"], list) else [server["gpu"]]
    assert gpus[0] == "L4" and set(gpus) <= GPU_NAMES and len(gpus) >= 2  # the cheapest first, with a backup in case Modal has no free L4
    assert server["port"] == 8000 and server["unauthenticated"] is True
    assert server["startup_timeout"] >= 10 * 60  # the first start downloads an 8 GB model
    assert len(server["secrets"]) == 1 and set(server["volumes"]) == {"/root/.cache/huggingface", "/root/.cache/vllm"}


def test_the_configuration_reaches_the_running_container_through_the_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, captured = load(monkeypatch, tmp_path, local=CONFIG)
    env = next(args[0] for name, args, _ in captured["calls"] if name == "env")
    assert env["MODEL3_BASE_REVISION"] == CONFIG["base_model_revision"] and env["MODEL3_ADAPTER_REPO"] == CONFIG["adapter_repo"]
    assert env["MODEL3_ADAPTER_REVISION"] == CONFIG["adapter_revision"] and env["MODAL_IS_REMOTE"] == "1"
    assert not any("token" in key.lower() or "key" in key.lower() for key in env)  # no secret is baked into the image
    secret_names = [args[0] for name, args, _ in captured["calls"] if name == "from_name" and args[0] == "cu-helpdesk-vllm"]
    assert secret_names == ["cu-helpdesk-vllm"]


def run_start(monkeypatch: pytest.MonkeyPatch, module: Any) -> tuple[list[str], dict[str, Any], Any]:
    downloads: dict[str, Any] = {}
    hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo: str, revision: str | None = None, token: str | None = None) -> str:
        downloads.update(repo=repo, revision=revision, token=token)
        return "/cache/hub/models--someone--cu-helpdesk-lora/snapshots/" + str(revision)

    hub.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    started: list[list[str]] = []

    class FakeProcess:
        terminated = False

        def __init__(self, command: list[str]) -> None:
            started.append(command)

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(module.subprocess, "Popen", FakeProcess)
    monkeypatch.setenv("HF_TOKEN", "test-hf-token")
    monkeypatch.setenv("VLLM_API_KEY", "test-vllm-key")
    server = module.Server()
    server.start()
    return started[0], downloads, server


def test_the_adapter_is_fetched_at_its_exact_commit_with_the_secret_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load(monkeypatch, tmp_path, local=CONFIG)
    _, downloads, _ = run_start(monkeypatch, module)
    assert downloads == {"repo": CONFIG["adapter_repo"], "revision": CONFIG["adapter_revision"], "token": "test-hf-token"}


def test_vllm_is_started_with_the_flags_the_endpoint_check_relies_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load(monkeypatch, tmp_path, local=CONFIG)
    command, _, _ = run_start(monkeypatch, module)

    def value_after(flag: str) -> str:
        return command[command.index(flag) + 1]

    assert command[:3] == ["vllm", "serve", "Qwen/Qwen3-4B-Instruct-2507"]
    assert value_after("--revision") == CONFIG["base_model_revision"]  # the base model is pinned to a commit too
    assert value_after("--api-key") == "test-vllm-key" and value_after("--port") == "8000" and value_after("--host") == "0.0.0.0"  # noqa: S104 - asserting the container binding, not binding anything
    assert "--enable-lora" in command and value_after("--max-model-len") == "4096"
    lora = json.loads(value_after("--lora-modules"))
    assert lora["name"] == "cu-helpdesk-lora" == module.ADAPTER_NAME  # what MODEL3_MODEL must be set to
    assert lora["base_model_name"] == "Qwen/Qwen3-4B-Instruct-2507"  # the JSON form: /v1/models then reports the parent
    assert lora["path"].endswith("/snapshots/" + CONFIG["adapter_revision"])


def test_the_lora_rank_limit_covers_the_trained_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load(monkeypatch, tmp_path, local=CONFIG)
    manifest = REPO_ROOT / "data" / "peft" / "adapter_manifest.json"
    if not manifest.is_file():
        pytest.skip("the adapter has not been trained yet")
    assert json.loads(manifest.read_text(encoding="utf-8"))["lora"]["r"] <= module.MAX_LORA_RANK  # vLLM refuses an adapter above --max-lora-rank


def test_stopping_terminates_the_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load(monkeypatch, tmp_path, local=CONFIG)
    _, _, server = run_start(monkeypatch, module)
    server.stop()
    assert server.process.terminated is True


def test_no_secret_value_is_written_in_the_file() -> None:
    assert 'os.environ["HF_TOKEN"]' in SOURCE and 'os.environ["VLLM_API_KEY"]' in SOURCE
    for line in SOURCE.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("HF_TOKEN =", "VLLM_API_KEY =")), line
    assert "hf_" not in SOURCE.replace("hf_cache", "").replace("hf_username", "").replace("HF_", "").replace("hf-", "")
