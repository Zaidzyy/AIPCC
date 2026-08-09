"""API keys for machine callers.

Why this exists: n8n runs the FIM engine on a schedule. Access tokens expire
after `ACCESS_TOKEN_EXPIRE_MINUTES` (60 by default), so a scheduled workflow
authenticated with a JWT starts failing an hour after somebody last pasted one
in. Raising the JWT lifetime to fix that would weaken every *human* session at
the same time, which is the one thing this must not do. So machines get a
separate, revocable credential and humans keep short-lived tokens.

**A key is hashed with SHA-256, not bcrypt.** That is deliberate, and it is not
a relaxation of hard rule #3. Bcrypt is slow on purpose because a *password* is
low-entropy and guessable offline. An API key here is 32 bytes from
`secrets.token_bytes` — brute-forcing it is not a cost problem a hash function
can influence, and paying ~100 ms of bcrypt on every scheduled request buys
nothing. Passwords still go through bcrypt; see `core/security.py`.

Format: ``aipcc_<prefix>_<secret>``

The prefix is stored in clear and uniquely indexed, so verification is one
indexed lookup plus one constant-time compare — never a scan that hashes every
key in the table. It is also what the UI shows, so a key is identifiable after
its secret is gone.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import NamedTuple

PREFIX = "aipcc"
SEPARATOR = "_"
PREFIX_BYTES = 6
SECRET_BYTES = 32


class GeneratedKey(NamedTuple):
    """A freshly minted key. `secret` is the only time the full value exists."""

    secret: str
    prefix: str
    key_hash: str


def generate_key() -> GeneratedKey:
    prefix = secrets.token_hex(PREFIX_BYTES)
    secret_part = secrets.token_urlsafe(SECRET_BYTES)
    secret = f"{PREFIX}{SEPARATOR}{prefix}{SEPARATOR}{secret_part}"
    return GeneratedKey(secret=secret, prefix=prefix, key_hash=hash_key(secret))


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def looks_like_api_key(credential: str) -> bool:
    """True for our key format. Used to route a bearer credential.

    A JWT never starts with this prefix, so the two credential types cannot be
    confused for one another.
    """
    return credential.startswith(f"{PREFIX}{SEPARATOR}")


def extract_prefix(secret: str) -> str | None:
    """The indexed lookup component, or None if the value is malformed.

    Split with `maxsplit=2`, not on every separator. `token_urlsafe` draws from
    the base64url alphabet, which includes `_`, so roughly two secrets in three
    contain one — an unbounded split then produced four or more parts, the
    length check rejected the key, and a perfectly valid credential 401'd about
    two thirds of the time.
    """
    parts = secret.split(SEPARATOR, 2)
    if len(parts) != 3 or parts[0] != PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1]


def verify_key(secret: str, key_hash: str) -> bool:
    """Constant-time comparison against a stored hash."""
    return secrets.compare_digest(hash_key(secret), key_hash)
