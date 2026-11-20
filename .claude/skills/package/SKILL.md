---
name: package
description: Build the clean submission ZIP of the repository (no secrets, runtime data, venvs, node_modules or weights) after the quality gate passes.
disable-model-invocation: true
---

# Package the repository

1. Run the `/verify` checks; stop if anything fails.
2. Run `python scripts/package_repo.py` (it re-runs the secret scan and refuses to package on findings).
3. List the ZIP contents (`python -m zipfile -l <zip>`) and confirm it contains no `.env`, `secrets/`, `storage/`,
   `*.db`, `node_modules/`, `.venv/`, adapter weights or real university documents.
4. Write or update `BUILD_REPORT.md`: features implemented per phase, commands run with results, known limitations,
   and setup steps still requiring the user's credentials or documents.
