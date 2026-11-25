"""Give the demo applicant CUAPP-DEMO-0001 your own address, in place: no table is dropped, so Drive indexing history, feedback and the
email audit survive (re-seeding with `seed_demo_db.py --yes` would drop them).

Usage (from the repo root, backend venv active):
    python scripts/set_demo_email.py                    # uses DEMO_APPLICANT_EMAIL from .env
    python scripts/set_demo_email.py --email you@gmail.com

Afterwards, in the chat, verify as CUAPP-DEMO-0001 with that address. The interview email is sent to it (and only to it): the recipient is read
from the database inside the send function, and EMAIL_RECIPIENT_ALLOWLIST must contain it before real sending will do anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.seed import DEMO_EMAIL_APPLICANT, set_demo_email  # noqa: E402
from app.db.session import make_engine  # noqa: E402
from app.domain.masking import mask_email  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default="", help="the address to use (default: DEMO_APPLICANT_EMAIL from .env)")
    args = parser.parse_args()
    settings = get_settings()
    email = (args.email or settings.demo_applicant_email).strip()
    if not email:
        print("No address given: use --email, or set DEMO_APPLICANT_EMAIL in .env.")
        return 2
    try:
        changed = set_demo_email(make_engine(settings.database_url), email)
    except ValueError as exc:
        print(f"Not changed: {exc}")
        return 2
    if not changed:
        print(f"{DEMO_EMAIL_APPLICANT} does not exist: seed the database first (python scripts/seed_demo_db.py --yes).")
        return 1
    print(f"{DEMO_EMAIL_APPLICANT} now has the registered address {mask_email(email)}.")
    if email.lower() not in [entry.lower() for entry in settings.allowlist]:
        print("Note: that address is not in EMAIL_RECIPIENT_ALLOWLIST, so real sending will refuse it until you add it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
