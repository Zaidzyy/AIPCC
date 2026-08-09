"""FastAPI application factory.

Note what is *absent*: this module does not create schema, does not seed, and
does not insert a user. Startup is side-effect free. Schema comes from
`alembic upgrade head`; demo data comes from `python -m app.db.seed`, run
deliberately.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import health
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="AI-Powered Cybersecurity Co-Pilot",
        version="0.1.0",
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    return app


app = create_app()
