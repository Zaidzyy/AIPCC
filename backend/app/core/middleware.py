"""Response security headers.

Written as a pure ASGI middleware rather than with `BaseHTTPMiddleware`. The
latter wraps every response in an anonymous task and re-emits the body, which
is a lot of machinery to add to every request in the app in order to append six
constant headers — and it is the layer that historically interferes with
streaming responses and background tasks. Mutating the `http.response.start`
message directly is both smaller and cheaper.

**Two policies, because the API and its docs are different documents.** The API
answers JSON to a fetch, so it gets `default-src 'none'` — there is no
legitimate resource for an API response to load, and the strictest possible
policy costs nothing. FastAPI's `/docs` is a real HTML page that pulls Swagger
UI from a CDN and runs inline bootstrap script, so the strict policy renders it
as a blank page. That is not a hypothetical: it is what shipping one CSP for
the whole app actually does, and it is only visible in a browser.

**The SPA's CSP is not set here.** It is served by Vite, not by FastAPI, so its
policy lives in `frontend/vite.config.js` next to the server that sends it.

HSTS is emitted only over HTTPS (or in production behind a TLS terminator).
Sending it over plain `http://localhost` is both spec-forbidden and a genuine
foot-gun: a browser that caches HSTS for `localhost` will refuse plain HTTP for
*every* project on that machine, and the user cannot easily tell what did it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.config import settings

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

# Two years, the value the preload list requires.
HSTS = "max-age=63072000; includeSubDomains"

# An API response has no legitimate reason to load anything at all.
API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# Swagger UI and ReDoc: FastAPI serves them from jsDelivr with an inline
# bootstrap script. Narrowed to that origin rather than opened to '*', and
# still `frame-ancestors 'none'`.
_DOCS_CDN = "https://cdn.jsdelivr.net"
DOCS_CSP = (
    "default-src 'none'; "
    f"script-src 'self' {_DOCS_CDN} 'unsafe-inline'; "
    f"style-src 'self' {_DOCS_CDN} 'unsafe-inline'; "
    f"font-src 'self' {_DOCS_CDN} data:; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'"
)

DOCS_PATHS = ("/docs", "/redoc")

# Everything this app does not use is turned off, so a future XSS cannot ask
# for a camera the app never wanted.
PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(self), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), usb=()"
)

BASE_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    # `no-referrer` rather than `strict-origin-when-cross-origin`: a report URL
    # carries a report id and a share URL carries a capability token, and
    # neither should reach a third-party host in a Referer header.
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", PERMISSIONS_POLICY),
    # `frame-ancestors` in CSP supersedes this for modern browsers; it stays
    # for the ones that never implemented that directive.
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


def headers_for(path: str, scheme: str) -> list[tuple[str, str]]:
    """The header set for one response. Pure, so it is testable without a server."""
    headers = list(BASE_HEADERS)
    headers.append(
        ("Content-Security-Policy", DOCS_CSP if _is_docs(path) else API_CSP)
    )
    if scheme == "https" or settings.environment == "production":
        headers.append(("Strict-Transport-Security", HSTS))
    return headers


def _is_docs(path: str) -> bool:
    # `/openapi.json` is data, not a page, so it keeps the strict policy.
    return any(path == p or path.startswith(p + "/") for p in DOCS_PATHS)


class SecurityHeadersMiddleware:
    """Append the security headers to every HTTP response."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Lowercased on the wire. HTTP/1.1 field names are case-insensitive,
        # but HTTP/2 requires lowercase, and everything else in the ASGI stack
        # already emits them that way.
        additions = [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers_for(scope.get("path", ""), scope.get("scheme", "http"))
        ]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = message.setdefault("headers", [])
                # Never overwrite: a route that has deliberately set its own
                # CSP or framing policy for one response knows something this
                # middleware does not.
                present = {name.lower() for name, _ in raw}
                raw.extend((name, value) for name, value in additions if name not in present)
            await send(message)

        await self.app(scope, receive, send_with_headers)
