"""OpenTelemetry tracing.

Four things are traced, chosen because they are the four places a report
generation actually spends time: the HTTP request, every SQL statement,
retrieval from Chroma, and each LLM call. The first two come from
instrumentation packages; the last two are hand-written spans, because there is
no off-the-shelf instrumentation for "the thing this application does".

The point of it is one picture: a single `report.generate` span with five
`llm.complete` children that **overlap**. That is the proof that the concurrent
section generation is concurrent — a claim this project has made since Phase 1
and could not previously show. `tests/test_observability.py` asserts exactly
that shape against an in-memory exporter, so the claim is checked on every run
rather than eyeballed once in a UI.

**Off by default.** The console exporter prints a multi-line span dump per
span; with tracing on out of the box, `docker compose up` produces an
unreadable wall of JSON and the first thing anyone would do is turn it off.
`OTEL_ENABLED=true` turns it on, and `OTEL_EXPORTER_OTLP_ENDPOINT` sends it
somewhere that can draw it — there is a Jaeger service behind the optional
`tracing` compose profile, so the default `docker compose up` stays one command
with four containers.

Span attributes never carry a prompt, a completion, or document content. Token
counts, model names, latencies and section names — the shape of the work, not
the data it was done on.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Tracer

from app.core.config import settings

logger = logging.getLogger(__name__)

_configured = False


def get_tracer(name: str = "aipcc") -> Tracer:
    """A tracer that is a no-op until `configure_tracing` has run.

    Callers never check whether tracing is enabled — the API's own no-op
    provider handles that. A `if settings.otel_enabled:` at each span site
    would be five more places to get the condition wrong.
    """
    return trace.get_tracer(name)


def configure_tracing(app: object | None = None) -> None:
    """Install the provider and instrument FastAPI and SQLAlchemy."""
    global _configured
    if _configured or not settings.otel_enabled:
        return

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.environment,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(_exporter()))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.db.session import engine

        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception:  # pragma: no cover - depends on optional packages
        # Instrumentation failing must not stop the application booting.
        # Observability is how you find out something is wrong; it is not
        # allowed to be the thing that is wrong.
        logger.exception("tracing instrumentation failed; continuing without it")

    _configured = True
    logger.info(
        "tracing enabled",
        extra={"exporter": "otlp" if settings.otel_exporter_otlp_endpoint else "console"},
    )


def _exporter():
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return ConsoleSpanExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
