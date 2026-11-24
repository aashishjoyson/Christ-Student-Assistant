"""Delete operational data that is older than its retention period.

  python scripts/retention.py --dry-run          # say what would be removed
  python scripts/retention.py                    # remove it

Periods: request traces 90 days, thumbs 365 days, stored conversations CHAT_HISTORY_RETENTION_DAYS (30 by default; only exists if CHAT_HISTORY_PERSIST was on).
Not touched: the indexed documents, the applicant database, evaluation runs and baselines. Run it while the API is quiet (a cron job at night).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.session import init_db, make_engine, make_session_factory  # noqa: E402
from app.domain.clock import utcnow  # noqa: E402
from app.services.history_store import HistoryStore  # noqa: E402
from app.services.retention import prune_traces, purge_feedback  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace-days", type=int, default=90)
    parser.add_argument("--feedback-days", type=int, default=365)
    parser.add_argument("--history-days", type=int, help="default: CHAT_HISTORY_RETENTION_DAYS")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    now = utcnow()
    verb = "would remove" if args.dry_run else "removed"

    kept, dropped = prune_traces(settings.trace_dir / "requests.jsonl", now - timedelta(days=args.trace_days), args.dry_run)
    print(f"traces older than {args.trace_days} days: {verb} {dropped}, keep {kept}")

    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        removed = purge_feedback(session, now - timedelta(days=args.feedback_days), args.dry_run)
    print(f"ratings older than {args.feedback_days} days: {verb} {removed}")

    days = args.history_days or settings.chat_history_retention_days
    if args.dry_run:
        print(f"stored conversations older than {days} days: not counted in a dry run")
    else:
        print(f"stored conversations older than {days} days: removed {HistoryStore(factory).purge(days)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
