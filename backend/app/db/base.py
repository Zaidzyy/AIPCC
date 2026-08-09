"""Declarative base.

Kept in its own module so `models.py` and Alembic's `env.py` can both import
`Base` without pulling in the engine (and therefore without touching a live
database at import time).
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
