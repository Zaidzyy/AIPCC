"""Explicit, manual seed script.

Run deliberately — never on startup:

    python -m app.db.seed              # admin user + sample document row
    python -m app.db.seed --ingest     # also embed the sample CSV into Chroma
    python -m app.db.seed --demo       # also write six weeks of demo reports
    python -m app.db.seed --service-token   # also mint an API key for n8n
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
import secrets
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
ADMIN_PASSWORD = "admin"
# `--demo` also creates an analyst, so a reviewer can log in as a non-admin and
# watch the ownership scoping do its job: the same dashboard, smaller numbers.
ANALYST_EMAIL = "analyst@aipcc.io"
ANALYST_PASSWORD = "analyst"
# The account the n8n workflows authenticate as. It has no usable password —
# see `seed_service_account` — because it is not meant to be logged into.
SERVICE_EMAIL = "n8n@aipcc.io"
SAMPLE_CSV = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic_pegasus_dataset.csv"
)

SEEDED_EMAILS = (ADMIN_EMAIL, ANALYST_EMAIL, SERVICE_EMAIL)


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


def seed_service_account(db) -> str:
    """Create the n8n service account and mint it a fresh API key.

    The account is an admin because the FIM engine polls `/get_all_reports`,
    which is scoped — a non-admin service account would only ever audit its own
    reports, which is the opposite of what a monitoring workflow is for.

    Its password hash is a random value nobody holds, so the account cannot be
    logged into through `/auth/login` at all. It authenticates only with an API
    key, and API keys are refused by the routes that manage users and
    credentials (`require_human`). A leaked key can therefore read and write
    report data, and cannot escalate.

    Re-running mints a new key and revokes the previous ones: the old secret
    was shown exactly once and cannot be recovered, so there is nothing to be
    gained by keeping it alive.
    """
    from app.core.api_key import generate_key
    from app.db.models import ApiKey

    service = db.scalar(select(Users).where(Users.email == SERVICE_EMAIL))
    if service is None:
        service = Users(
            first_name="n8n",
            last_name="Service",
            email=SERVICE_EMAIL,
            role="admin",
            status="Active",
            # Not a password anyone knows — this account has no login path.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            organization="AIPCC",
            location="UAE",
            bio="Service account for the n8n Orchestrator and FIM workflows.",
        )
        db.add(service)
        db.flush()
        print(f"created service account: {service.email} ({service.user_id})")

    revoked = 0
    for existing in db.scalars(select(ApiKey).where(ApiKey.user_id == service.user_id)):
        if not existing.revoked:
            existing.revoked = True
            revoked += 1

    generated = generate_key()
    db.add(
        ApiKey(
            name="n8n workflows",
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            user_id=service.user_id,
        )
    )
    db.flush()

    if revoked:
        print(f"revoked {revoked} previously issued key(s) for {SERVICE_EMAIL}")
    return generated.secret


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
        "--service-token",
        action="store_true",
        help="create the n8n service account and print a fresh API key (revokes its old ones)",
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

        service_key = seed_service_account(db) if args.service_token else None

        db.commit()

        if service_key:
            print()
            print("n8n API key (shown once — only its SHA-256 is stored):")
            print(f"  {service_key}")
            print("  Use it in n8n as a Header Auth credential:")
            print(f"    Authorization: Bearer {service_key}")
            print()

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
