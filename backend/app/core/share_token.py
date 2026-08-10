"""Bearer tokens for read-only report share links.

A share token is a **capability**, not a credential. Holding one does not make
you anybody: it authorizes exactly one action — read this one report — for
whoever presents it. That distinction drives every decision below.

**It is not a JWT for the owning user.** Minting a token that resolves to the
report's owner would mean a link forwarded to a contractor carries the owner's
whole account with it: every other report, the dashboard, the upload endpoint.
A share token never reaches `get_current_user`; it is only ever read from the
path of `/share/{token}`, and the routes that accept it read exactly one row.

**It is not an API key either**, and deliberately does not reuse
`core/api_key.py`. The two look alike — a clear indexed prefix plus a hashed
secret — but they answer different questions. An API key answers "which
principal is calling"; a share token answers "may this request see this row".
Merging them would put the capability into the `Authorization` header, one
`looks_like_*` bug away from being treated as an identity. The `shr_` namespace
cannot collide with `aipcc_`, so a share token pasted into an Authorization
header is rejected as a malformed JWT rather than resolved as anything.

Format: ``shr_<prefix>_<secret>``

Only the SHA-256 is stored. The prefix is clear and uniquely indexed, so
resolving a link is one indexed lookup plus one constant-time compare — never a
scan that hashes every share in the table. The secret is 32 bytes from
`secrets.token_urlsafe`, which is the whole of the access control here, so it
has to be guess-proof rather than memorable.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import NamedTuple

PREFIX = "shr"
SEPARATOR = "_"
PREFIX_BYTES = 6
SECRET_BYTES = 32


class GeneratedToken(NamedTuple):
    """A freshly minted token. `token` is the only time the full value exists."""

    token: str
    prefix: str
    token_hash: str


def generate_token() -> GeneratedToken:
    prefix = secrets.token_hex(PREFIX_BYTES)
    secret_part = secrets.token_urlsafe(SECRET_BYTES)
    token = f"{PREFIX}{SEPARATOR}{prefix}{SEPARATOR}{secret_part}"
    return GeneratedToken(token=token, prefix=prefix, token_hash=hash_token(token))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_prefix(token: str) -> str | None:
    """The indexed lookup component, or None if the value is malformed.

    `maxsplit=2`, for the reason `core/api_key.py` documents at length:
    `token_urlsafe` draws from the base64url alphabet, so most secrets contain
    an underscore and an unbounded split rejects a perfectly valid token.
    """
    parts = token.split(SEPARATOR, 2)
    if len(parts) != 3 or parts[0] != PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1]


def verify_token(token: str, token_hash: str) -> bool:
    """Constant-time comparison against a stored hash."""
    return secrets.compare_digest(hash_token(token), token_hash)
