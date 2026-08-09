"""Explicit, manual seed script.

Run deliberately — never on startup:

    python -m app.db.seed              # admin user + sample document row
    python -m app.db.seed --ingest     # also embed the sample CSV into Chroma
    python -m app.db.seed --reset      # delete seeded rows first, then re-seed

`--ingest` is opt-in because it loads the MiniLM embedding model, which is a
slow first-run download.

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
SAMPLE_CSV = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic_pegasus_dataset.csv"


def seed_admin(db) -> Users:
    existing = db.scalar(select(Users).where(Users.email == ADMIN_EMAIL))
    if existing:
        print(f"admin user already present: {existing.email} ({existing.user_id})")
        return existing

    admin = Users(
        first_name="AIPCC",
        last_name="Admin",
        email=ADMIN_EMAIL,
        role="admin",
        status="Active",
        phone_number="+971000000000",
        password_hash=hash_password(ADMIN_PASSWORD),
        organization="AIPCC",
        location="UAE",
        bio="Seeded administrator account.",
    )
    db.add(admin)
    db.flush()
    print(f"created admin user: {admin.email} / {ADMIN_PASSWORD} ({admin.user_id})")
    return admin


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
    admin = db.scalar(select(Users).where(Users.email == ADMIN_EMAIL))
    if admin:
        db.delete(admin)
        db.flush()
        print("deleted existing seed data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed AIPCC demo data.")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="also embed the sample CSV into Chroma (downloads the embedding model)",
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
