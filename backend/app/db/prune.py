"""Drop rate-limit rows past their usefulness.

    python -m app.db.prune              # older than AUTH_ATTEMPT_RETENTION_DAYS
    python -m app.db.prune --days 7

Postgres has no per-row TTL, which is the honest cost of keeping rate-limit
state in the database instead of Redis. Nothing here runs automatically: the
index makes the window query cheap regardless of table size, so an unpruned
table is a disk-space problem rather than a correctness one, and a background
sweeper that nobody knows about is worse than a documented command.

**This touches `auth_attempts` and nothing else.** The audit log has no
equivalent and cannot acquire one — a Postgres trigger refuses DELETE on that
table, so an attempt to add "prune old audit entries" here fails loudly rather
than quietly eroding the record.
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import ratelimit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=settings.auth_attempt_retention_days,
        help="delete attempts older than this many days",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        removed = ratelimit.prune(db, older_than=timedelta(days=args.days))

    print(f"pruned {removed} auth attempt(s) older than {args.days} day(s)")


if __name__ == "__main__":
    main()
