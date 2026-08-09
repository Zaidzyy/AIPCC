"""Explicit, manual seed script.

Run deliberately — never on startup:

    python -m app.db.seed              # admin user + sample document row
    python -m app.db.seed --ingest     # also embed the sample CSV into Chroma
    python -m app.db.seed --demo       # also write six weeks of demo reports
    python -m app.db.seed --reset      # delete seeded rows first, then re-seed

`--ingest` is opt-in because it loads the MiniLM embedding model, which is a
slow first-run download.

`--demo` is opt-in because it writes a lot of rows. It calls no LLM — every
value comes from the fixed-seed fixtures in `app.db.demo_data` — and it is what
makes the dashboard worth looking at on a fresh install.

Assumes the schema already exists (`alembic upgrade head`). This script does
not create tables.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Document, Users
from app.db.session import SessionLocal

# Not a .local / .test / .invalid address: those are reserved special-use
# domains and `EmailStr` rejects them, so a seeded admin using one could not be
# serialized by the API that is supposed to return it.
ADMIN_EMAIL = "admin@aipcc.io"
ADMIN_PASSWORD = "admin"  # noqa: S105 — local demo credential, documented in README
# `--demo` also creates an analyst, so a reviewer can log in as a non-admin and
# watch the ownership scoping do its job: the same dashboard, smaller numbers.
ANALYST_EMAIL = "analyst@aipcc.io"
ANALYST_PASSWORD = "analyst"  # noqa: S105 — local demo credential
SAMPLE_CSV = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic_pegasus_dataset.csv"

SEEDED_EMAILS = (ADMIN_EMAIL, ANALYST_EMAIL)


def _seed_user(db, *, email: str, password: str, role: str, first: str, last: str) -> Users:
    existing = db.scalar(select(Users).where(Users.email == email))
    if existing:
        print(f"{role} user already present: {existing.email} ({existing.user_id})")
        return existing

    user = Users(
        first_name=first,
        last_name=last,
        email=email,
        role=role,
        status="Active",
        phone_number="+971000000000",
        password_hash=hash_password(password),
        organization="AIPCC",
        location="UAE",
        bio=f"Seeded {role} account.",
    )
    db.add(user)
    db.flush()
    print(f"created {role} user: {user.email} / {password} ({user.user_id})")
    return user


def seed_admin(db) -> Users:
    return _seed_user(
        db,
        email=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
        role="admin",
        first="AIPCC",
        last="Admin",
    )


def seed_analyst(db) -> Users:
    return _seed_user(
        db,
        email=ANALYST_EMAIL,
        password=ANALYST_PASSWORD,
        role="analyst",
        first="Demo",
        last="Analyst",
    )


def seed_sample_document(db, owner: Users) -> Document | None:
    if not SAMPLE_CSV.exists():
        print(f"sample dataset not found at {SAMPLE_CSV}, skipping document seed")
        return None

    existing = db.scalar(
        select(Document).where(
            Document.user_id == owner.user_id, Document.document_name == SAMPLE_CSV.name
        )
    )
    if existing:
        print(f"sample document already present: {existing.document_name} ({existing.document_id})")
        return existing

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.upload_dir / SAMPLE_CSV.name
    shutil.copyfile(SAMPLE_CSV, destination)

    now = datetime.now(timezone.utc)
    document = Document(
        document_name=SAMPLE_CSV.name,
        document_size=float(destination.stat().st_size),
        document_extension=SAMPLE_CSV.suffix,
        document_path=str(destination),
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=owner.user_id,
    )
    db.add(document)
    db.flush()
    print(f"created sample document: {document.document_name} ({document.document_id})")
    return document


def reset(db) -> None:
    """Delete seeded rows. Cascades remove dependent documents/reports/chats."""
    deleted = 0
    for email in SEEDED_EMAILS:
        user = db.scalar(select(Users).where(Users.email == email))
        if user:
            db.delete(user)
            deleted += 1
    if deleted:
        db.flush()
        print(f"deleted existing seed data for {deleted} user(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed AIPCC demo data.")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="also embed the sample CSV into Chroma (downloads the embedding model)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="write six weeks of deterministic demo reports so the dashboard is populated",
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete seeded rows before seeding"
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.reset:
            reset(db)

        admin = seed_admin(db)
        document = seed_sample_document(db, admin)

        if args.demo:
            # Imported here so a plain seed does not pull in the fixture module.
            from app.db.demo_data import seed_demo

            analyst = seed_analyst(db)
            counts = seed_demo(db, [admin, analyst])
            print(
                f"demo data: {counts['reports']} reports, {counts['documents']} documents, "
                f"{counts['findings']} findings across 2 users"
            )
            print(
                "  demo documents are registered but not embedded — generate new "
                f"reports from {SAMPLE_CSV.name} (seeded with --ingest)"
            )

        db.commit()

        if args.ingest and document is not None:
            # Imported here so the default path never loads the embedding model.
            from app.services.rag.ingest import ingest

            chunks = ingest(
                document.document_path,
                document.document_extension,
                str(document.document_id),
            )
            print(f"ingested {chunks} chunks into Chroma at {settings.chroma_dir}")

    print("seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
