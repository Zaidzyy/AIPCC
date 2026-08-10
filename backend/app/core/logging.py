"""Structured logging.

JSON in `ci` and `production`, human-readable in `local` — driven by the
existing `ENVIRONMENT` setting rather than a second switch that can disagree
with it. `LOG_FORMAT` pins either one when you need to reproduce a log-parsing
problem on a laptop.

Every line carries the correlation id, pulled from the `ContextVar` by a
filter rather than passed at each call site. A logging call that has to
remember to include the id is a logging call that will not.

**One access line per request, ours rather than uvicorn's.** Uvicorn's is
unstructured, carries no actor and no correlation id, and cannot be made to;
running both would double every request in the log. It is switched off in
`configure_logging` and replaced by `AccessLogMiddleware` below, which knows
things uvicorn cannot: who the caller was, and whether they were a person or a
machine.

**What is never logged:** request bodies, response bodies, headers,
`Authorization` in any form, and document contents. The access line carries the
route *template* (`/reports/{report_id}`), not the resolved path, so an id
never becomes a distinct log key — and the query string is dropped entirely,
because that is where a token would be if anyone ever put one there.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.config import settings
from app.core.correlation import get_correlation_id

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]

# Attributes present on every LogRecord. Anything not in here was passed by a
# call site as `extra=` and belongs in the structured output.
_STANDARD = frozenset(
    (
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
        "correlation_id",
    )
)

ACCESS_LOGGER = "aipcc.access"


class CorrelationFilter(logging.Filter):
    """Attach the current correlation id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str` rather than a custom encoder: a UUID or a datetime in an
        # `extra=` should not be able to take down logging. A log line is not
        # the place to raise.
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable in a terminal, with the correlation id kept short."""

    def format(self, record: logging.LogRecord) -> str:
        correlation_id = getattr(record, "correlation_id", None)
        prefix = f"[{correlation_id[:8]}] " if correlation_id else ""
        stamp = self.formatTime(record, "%H:%M:%S")
        base = f"{stamp} {record.levelname:<7} {prefix}{record.getMessage()}"
        extras = " ".join(
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _STANDARD and not key.startswith("_")
        )
        if extras:
            base = f"{base}  {extras}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def use_json() -> bool:
    if settings.log_format == "json":
        return True
    if settings.log_format == "console":
        return False
    return not settings.is_local


def configure_logging() -> None:
    """Install the root handler. Idempotent — safe if the app factory runs twice."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if use_json() else ConsoleFormatter())
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Uvicorn's access log is replaced, not supplemented — see the module
    # docstring. Its error logger keeps its records but loses its own handler,
    # so startup messages come out in our format instead of two.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


class AccessLogMiddleware:
    """One structured line per request."""

    def __init__(self, app: Callable[[Scope, Any, Any], Awaitable[None]]) -> None:
        self.app = app
        self.logger = logging.getLogger(ACCESS_LOGGER)

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            state = scope.get("state", {})
            # The route *template*, so `/reports/{report_id}` is one log key
            # rather than one per report. Resolved by the router, so it only
            # exists once the request has been matched — a 404 has no route.
            route = scope.get("route")
            self.logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "route": getattr(route, "path", None) or scope.get("path"),
                    "status": status_holder.get("status"),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "actor_id": state.get("actor_id"),
                    # "was this a person or a workflow" — the distinction the
                    # audit log makes, made the same way here.
                    "actor_type": state.get("auth_method"),
                    "client_ip": _client(scope),
                },
            )


def _client(scope: Scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None
