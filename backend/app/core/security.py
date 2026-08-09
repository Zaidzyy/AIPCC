"""Password hashing.

Phase 0 needs this so `seed.py` can create its admin user without ever writing
a plaintext password (CLAUDE.md > Hard rules #3). Phase 2 adds JWT creation /
verification and the `get_current_user` / `require_role` dependencies here.
"""

import bcrypt


def hash_password(password: str) -> str:
    """Return a bcrypt hash of `password`."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check `password` against a stored bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
