"""The secret scan tolerates a developer's own ignored .env / secrets/ key, and nothing else."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_secrets.py"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the scan asks git whether a file is ignored")


def scan(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True, check=False)  # noqa: S603


def repo(tmp_path: Path, gitignore: str) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)  # noqa: S603, S607
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    return tmp_path


def write(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_an_ignored_key_in_the_root_secrets_folder_passes(tmp_path: Path) -> None:
    root = repo(tmp_path, "secrets/\n")
    write(root, "secrets/drive-service-account.json")
    result = scan(root)
    assert result.returncode == 0, result.stdout


def test_the_same_key_fails_once_git_stops_ignoring_it(tmp_path: Path) -> None:
    root = repo(tmp_path, "# secrets/ is no longer ignored\n")
    write(root, "secrets/drive-service-account.json")
    result = scan(root)
    assert result.returncode == 1 and "secrets/drive-service-account.json" in result.stdout


def test_a_key_anywhere_else_always_fails_even_if_ignored(tmp_path: Path) -> None:
    root = repo(tmp_path, "secrets/\nconfig/\n")
    write(root, "config/drive-service-account.json")
    result = scan(root)
    assert result.returncode == 1 and "config/drive-service-account.json" in result.stdout


def test_an_ignored_root_env_passes_and_an_unignored_one_fails(tmp_path: Path) -> None:
    ignored, exposed = tmp_path / "ignored", tmp_path / "exposed"
    ignored.mkdir()
    exposed.mkdir()
    for root, gitignore in ((ignored, ".env\n"), (exposed, "# nothing ignored\n")):
        repo(root, gitignore)
        (root / ".env").write_text("X=1", encoding="utf-8")
    assert scan(ignored).returncode == 0
    assert scan(exposed).returncode == 1
