"""Local operator commands.

    python -m app.cli init --demo
    python -m app.cli seed
    python -m app.cli sync
    python -m app.cli report --start 2026-11-01 --end 2026-11-08
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import Base, SessionLocal, engine
from app.seed import init_database, seed_all
from app.models import DataSource
from app.services.ingestion import get_source, run_mock_sync
from app.services.reports import generate_weekly

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _create_schema() -> None:
    Base.metadata.create_all(bind=engine)
    # A database created with create_all has no Alembic version row. Adopt it at
    # head so the documented `alembic upgrade head && alembic check` flow works
    # after `make seed`.
    if "alembic_version" not in inspect(engine).get_table_names():
        command.stamp(_alembic_config(), "head")


def main() -> None:
    parser = argparse.ArgumentParser(prog="trendscope")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the schema and seed reference data")
    init.add_argument("--demo", action="store_true", help="also run a mock sync")
    init.add_argument("--force-sync", action="store_true", help="sync even if a demo run exists")

    sub.add_parser("seed", help="seed reference data without running a sync")

    sync = sub.add_parser("sync", help="run a mock sync now")
    sync.add_argument("--as-of", type=date.fromisoformat, default=None)

    report = sub.add_parser("report", help="generate a weekly report")
    report.add_argument("--start", type=date.fromisoformat, default=None)
    report.add_argument("--end", type=date.fromisoformat, default=None)
    report.add_argument("--country", default="AU")

    args = parser.parse_args()
    _create_schema()

    with SessionLocal() as db:
        if args.command == "init":
            if args.demo:
                source = get_source(db, "mock")
                if source is not None and source.last_sync_at is not None and not args.force_sync:
                    result = seed_all(db)
                else:
                    result = init_database(db, demo=True)
            else:
                result = seed_all(db)
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "seed":
            print(json.dumps(seed_all(db), indent=2, default=str))
        elif args.command == "sync":
            source = get_source(db, "mock")
            if source is None:
                raise SystemExit("Mock source missing; run `python -m app.cli seed` first.")
            run = run_mock_sync(db, source=source, as_of=args.as_of)
            print(
                json.dumps(
                    {
                        "run": str(run.id),
                        "status": run.status,
                        "fetched": run.records_fetched,
                        "written": run.records_written,
                        "rejected": run.records_rejected,
                    },
                    indent=2,
                )
            )
        elif args.command == "report":
            end = args.end or date.today()
            start = args.start or (end - timedelta(days=7))
            report_row = generate_weekly(db, args.country.upper(), start, end)
            print(
                json.dumps(
                    {
                        "report": str(report_row.id),
                        "status": report_row.status,
                        "summary": report_row.summary,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
