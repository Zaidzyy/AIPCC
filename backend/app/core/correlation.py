"""Request correlation.

One id per request, carried three places: the `X-Request-ID` response header,
every log line, and every audit row. That is what makes an audit entry
answerable — "what else happened in the request that changed this
classification" is a question the log can only answer if both sides share a key.

The id lives in a `ContextVar`, not in a parameter. Threading it through
`generate_report` → `generate_section` → `LLMProvider.complete` would put an
observability concern in the signature of every function it passes, and the
first place someone forgot to pass it would be a silent hole rather than an
error. `contextvars` propagates into `asyncio.gather` tasks and across
`asyncio.to_thread` automatically, which is exactly the fan-out this app uses
for concurrent section generation.

**An inbound id is untrusted input.** It arrives in a header, and it ends up in
a response header and in log records. Echoed unvalidated, a newline in it
forges a second log line and a CR forges a second HTTP header. It is therefore
filtered to a conservative character set and truncated, and replaced outright
if nothing survives.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

HEADER = "x-request-id"

# Hex, dashes and underscores. Wide enough for a uuid, a ULID or a trace id
# from an upstream proxy; narrow enough that nothing in it can be a delimiter
# in a log line, a header, or a JSON string.
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
MAX_LENGTH = 64

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]


def new_id() -> str:
    return uuid.uuid4().hex


def sanitize(raw: str | None) -> str | None:
    """Make an inbound id safe to echo, or reject it.

    Returns None when nothing usable is left, so the caller generates a fresh
    one rather than propagating an empty string that reads as "no correlation"
    everywhere downstream.
    """
    if not raw:
        return None
    cleaned = _SAFE.sub("", raw)[:MAX_LENGTH]
    return cleaned or None


def get_correlation_id() -> str | None:
    """The current request's id, or None outside a request (a CLI, a test)."""
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


class CorrelationIdMiddleware:
    """Accept or mint a correlation id, publish it, and return it."""

    def __init__(self, app: Callable[[Scope, Any, Any], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = _header(scope, HEADER)
        correlation_id = sanitize(inbound) or new_id()

        token = _correlation_id.set(correlation_id)
        # Also on `scope["state"]`, which is what `request.state` reads. The
        # ContextVar covers everything the request awaits; this covers the
        # handful of places that already take a `Request` — `services/audit`
        # among them — without them needing to know a ContextVar exists.
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (HEADER.encode("latin-1"), correlation_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id.reset(token)


def _header(scope: Scope, name: str) -> str | None:
    target = name.encode("latin-1")
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode("latin-1", errors="replace")
    return None
