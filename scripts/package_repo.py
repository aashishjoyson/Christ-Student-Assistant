"""Create a clean source ZIP (no secrets, runtime data, venvs, node_modules, weights).

Usage (from repo root): python scripts/package_repo.py [output.zip]
Runs the secret scan first and refuses to package if it fails.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache",
                ".ruff_cache", ".mypy_cache", "storage", "secrets", "mlruns", "adapters", "outputs", ".claude/worktrees"}
EXCLUDE_NAMES = {".env", ".DS_Store", "settings.local.json", "CLAUDE.local.md"}
EXCLUDE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".safetensors", ".bin", ".pt", ".zip", ".log"}


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts) or ".claude/worktrees" in rel.as_posix():
        return False
    posix = rel.as_posix()
    # Real university documents never go into a package: only the SYNTHETIC_ samples may.
    if posix.startswith("data/private/") or (posix.startswith("data/sample_docs/") and not path.name.startswith("SYNTHETIC_")):
        return False
    if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
        return False
    return not (path.name.startswith(".env.") and path.name != ".env.example")


def main() -> int:
    if subprocess.run([sys.executable, str(ROOT / "scripts" / "check_secrets.py"), str(ROOT)]).returncode != 0:  # noqa: S603
        print("Refusing to package: fix the secret scan findings first.")
        return 1
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "cu-student-helpdesk-repository.zip"
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and included(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, Path("cu-student-helpdesk") / path.relative_to(ROOT))
    print(f"Wrote {out} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
