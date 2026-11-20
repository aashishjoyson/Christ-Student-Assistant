"""Reset the database and load SYNTHETIC applicants.

Usage (from repo root, backend venv active):
    python scripts/seed_demo_db.py --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.seed import reset_and_seed  # noqa: E402
from app.db.session import make_engine  # noqa: E402
from app.domain.clock import utcnow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm that ALL applicant tables will be dropped")
    parser.add_argument("--csv", type=Path, default=REPO_ROOT / "data" / "synthetic_applicants.csv")
    args = parser.parse_args()
    if not args.yes:
        print("This drops and recreates every table in the configured database. Re-run with --yes.")
        return 1
    settings = get_settings()
    engine = make_engine(settings.database_url)
    count = reset_and_seed(engine, args.csv, settings.app_timezone, utcnow())
    print(f"Seeded {count} SYNTHETIC applicants into {settings.database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
