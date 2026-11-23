"""The seed script must work on a clean checkout, where storage/ does not exist yet."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.core.config import REPO_ROOT, Settings
from app.db.models import Applicant
from app.db.seed import reset_and_seed
from app.db.session import make_engine, make_session_factory
from tests.integration.conftest import SEED_NOW


def test_seed_creates_missing_database_directory(tmp_path: Path) -> None:
    db_file = tmp_path / "not" / "created" / "yet" / "helpdesk.db"
    assert not db_file.parent.exists()

    engine = make_engine(f"sqlite:///{db_file.as_posix()}")
    count = reset_and_seed(
        engine, REPO_ROOT / "data" / "synthetic_applicants.csv", Settings(_env_file=None).app_timezone, SEED_NOW  # type: ignore[call-arg]
    )

    assert count > 0
    assert db_file.exists()
    with make_session_factory(engine)() as session:
        stored = session.execute(select(func.count()).select_from(Applicant)).scalar_one()
        synthetic = session.execute(
            select(func.count()).select_from(Applicant).where(Applicant.is_synthetic.is_(True))
        ).scalar_one()
    assert stored == count
    assert synthetic == count  # every seeded row is labelled SYNTHETIC
