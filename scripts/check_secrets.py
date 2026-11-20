"""Fail if secret-looking strings or forbidden files are present in the repository tree.

Usage: python scripts/check_secrets.py [path]     (exit code 1 on findings)
Run before every commit and before packaging. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache",
             ".ruff_cache", "storage", ".mypy_cache"}
FORBIDDEN_FILES = [re.compile(p) for p in (
    r"^\.env$", r"^\.env\.(?!example$).+", r"client_secret.*\.json$", r"credentials.*\.json$",
    r"service[-_]?account.*\.json$", r"drive-token\.json$", r"token\.json$", r".*\.pem$", r".*\.p12$",
    r"adapter_model\.safetensors$", r".*\.db$", r".*\.sqlite3?$",
)]
SECRET_PATTERNS = {
    "openai/openrouter key": re.compile(r"sk-(?:proj-|or-v1-)?[A-Za-z0-9_\-]{20,}"),
    "google api key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "google oauth client secret": re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"),
    "hugging face token": re.compile(r"hf_[A-Za-z0-9]{30,}"),
    "smtp password assignment": re.compile(r"^SMTP_PASSWORD=\S+", re.MULTILINE),
}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".txt", ".toml", ".yaml", ".yml", ".csv", ".jsonl",
                 ".ipynb", ".html", ".css", ".example", ".cfg", ".ini", ".sh", ".ps1", ""}


def iter_files(root: Path):  # type: ignore[no-untyped-def]
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            yield path


def main() -> int:
    findings: list[str] = []
    for path in iter_files(ROOT):
        rel = path.relative_to(ROOT).as_posix()
        if any(p.search(path.name) for p in FORBIDDEN_FILES):
            findings.append(f"forbidden file: {rel}")
            continue
        if path.suffix not in TEXT_SUFFIXES or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {rel}")
    if findings:
        print("Secret scan FAILED:\n  " + "\n  ".join(findings))
        return 1
    print(f"Secret scan passed ({ROOT}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
