"""FastAPI application factory.

Note what is *absent*: this module does not create schema, does not seed, and
does not insert a user. Startup is side-effect free. Schema comes from
`alembic upgrade head`; demo data comes from `python -m app.db.seed`, run
deliberately.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    alerts,
    api_keys,
    auth,
    chat,
    dashboard,
    documents,
    health,
    reports,
    shares,
    users,
)
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
        # `Content-Disposition` is not a CORS-safelisted response header, so a
        # browser hides it from JavaScript unless it is named here. Without
        # this the export downloads correctly and silently lands as the client
        # fallback name — the header is sent, the fetch succeeds, and only the
        # filename is quietly wrong.
        expose_headers=["Content-Disposition"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(documents.router)
    app.include_router(reports.router)
    app.include_router(shares.router)
    app.include_router(chat.router)
    app.include_router(dashboard.router)
    app.include_router(alerts.router)
    app.include_router(api_keys.router)

    return app


app = create_app()
