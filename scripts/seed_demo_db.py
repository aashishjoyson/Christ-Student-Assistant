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
    parser.add_argument("--yes", action="store_true", help="confirm that EVERY table will be dropped (applicants, Drive indexing history, feedback, email audit)")
    parser.add_argument("--csv", type=Path, default=REPO_ROOT / "data" / "synthetic_applicants.csv")
    args = parser.parse_args()
    if not args.yes:
        print("This drops and recreates every table in the configured database, including the Drive indexing history and the feedback.")
        print("To only change the demo applicant's email address, use: python scripts/set_demo_email.py")
        print("Re-run with --yes to reset everything.")
        return 1
    settings = get_settings()
    engine = make_engine(settings.database_url)
    count = reset_and_seed(engine, args.csv, settings.app_timezone, utcnow(), demo_email=settings.demo_applicant_email or None)
    print(f"Seeded {count} SYNTHETIC applicants into {settings.database_url}")
    if settings.demo_applicant_email:
        print("CUAPP-DEMO-0001 uses the address from DEMO_APPLICANT_EMAIL (not shown here).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
