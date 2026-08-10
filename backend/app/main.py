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
    attack,
    audit,
    auth,
    chat,
    dashboard,
    documents,
    evaluation,
    health,
    reports,
    shares,
    users,
)
from app.core.config import settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.core.tracing import configure_tracing


def create_app() -> FastAPI:
    # Before anything else, so a failure during router import is logged in the
    # configured format rather than by whatever handler logging fell back to.
    configure_logging()

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

    # Added *after* CORS on purpose. `add_middleware` prepends, so the last one
    # added is the outermost — which is what puts the security headers on
    # responses no route ever sees: CORS preflights, which CORSMiddleware
    # answers by itself, and anything an exception handler produces.
    app.add_middleware(SecurityHeadersMiddleware)

    # Then the access log, then correlation — so correlation ends up outermost
    # of the three. `add_middleware` prepends, so the id is established before
    # the access log runs and is therefore on the line the access log writes;
    # reversing these two produces a request log with a null correlation id,
    # which is the one field it exists for.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

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
    app.include_router(audit.router)
    app.include_router(evaluation.router)
    app.include_router(attack.router)

    # Last, because instrumenting FastAPI wraps the finished middleware stack.
    # No-op unless OTEL_ENABLED — see `core/tracing.py` on why it is off by
    # default.
    configure_tracing(app)

    return app


app = create_app()
