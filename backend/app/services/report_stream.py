"""Streaming a report generation as it happens.

Five sections already ran concurrently — Phase 9 measured 94 ms of wall clock
against 459 ms summed — and a user watching a spinner could not tell. This
module is the seam that lets them watch.

**Why SSE and not WebSocket.** The traffic is one-directional and short-lived:
the server has things to say, the client has nothing to send back after the
request that started it. SSE is that shape exactly, it is plain HTTP so it
survives proxies and the CSP already in place, and it needs no second protocol
in the deployment story. A WebSocket would buy bidirectionality nobody wants
and cost an upgrade handshake that intermediaries mishandle.

**Why POST and not `EventSource`.** `EventSource` cannot set an `Authorization`
header, and the alternative is a token in the query string — which this project
refuses on principle and would be worse than a principle here, because
`core/logging.py` writes the request line for every call. So the stream is a
POST consumed with `fetch` and a `ReadableStream`. The client is slightly more
code; the token stays out of the URL, the access log and the browser history.

**Why generation does not live in the response generator.** The most likely
failure of a two-minute stream is that the client goes away — a sleeping
laptop, a closed tab, a proxy timeout. If the work were driven by the response
body, Starlette closing that generator would abandon a report mid-write. So the
generation *and its storage* run in a task with its own database session, and
the response generator only forwards what that task publishes. Hanging up
therefore costs the events, never the report: the row is already reserved, its
id went out in the first event, and `GET /reports/{id}/status` finishes the
story for whoever comes back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import Request

from app.db import models
from app.db.session import SessionLocal
from app.schemas.report import GenerateReportRequest
from app.services import audit
from app.services.report import SECTION_SPECS, SectionEvent, generate_report
from app.services.report_storage import fail_report, store_report

logger = logging.getLogger(__name__)

# Tasks are kept referenced here for exactly as long as they run. Without this
# the event loop holds only a weak reference and a long generation can be
# garbage-collected mid-flight — a documented asyncio foot-gun, and one whose
# symptom is a report that silently never appears.
_running: set[asyncio.Task] = set()

# Sent every 15 seconds while a section is still thinking. A section can take
# 30 s, and an idle connection is what proxies and load balancers reap; an SSE
# comment costs three bytes and is ignored by every client.
HEARTBEAT_SECONDS = 15.0


def open_session():
    """The generation task's own session.

    A function rather than a direct `SessionLocal()` call so the suite can bind
    the task to its rolled-back test session. Without that seam the streaming
    tests would be the only ones in the project writing rows the fixture cannot
    undo, and the developer's database would fill up with them.
    """
    return SessionLocal()


def sse(event: str, data: dict) -> bytes:
    """One SSE frame.

    `json.dumps` is what makes this safe: a raw newline inside a value would
    split one event into two malformed ones, and section errors carry model
    output, which is full of them.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


@dataclass
class _Progress:
    """The channel between the generation task and the response body."""

    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


def _event_payload(event: SectionEvent) -> dict:
    payload = {
        "section": event.section,
        "state": event.state,
        "attempt": event.attempt,
        "elapsed_ms": event.elapsed_ms,
    }
    if event.items is not None:
        payload["items"] = event.items
    if event.ungrounded is not None:
        payload["ungrounded"] = event.ungrounded
    if event.reason is not None:
        payload["reason"] = event.reason
    if event.error is not None:
        # The typed SectionError, not a string. The UI shows the stage and the
        # detail separately, and "which stage failed" is the difference between
        # a provider outage and a model that will not produce valid JSON.
        payload["error"] = event.error.model_dump()
    return payload


async def _generate_and_store(
    progress: _Progress,
    *,
    report_id: uuid.UUID,
    payload: GenerateReportRequest,
    user_id: uuid.UUID,
    request: Request,
) -> dict:
    """Run the whole generation, persist it, and return the terminal payload.

    Owns its own session deliberately: the request's session is tied to the
    response, and this outlives the response whenever a client hangs up.
    """
    db = open_session()
    try:
        result = await generate_report(
            str(payload.document_id), on_event=progress.queue.put
        )
        report = db.get(models.Report, report_id)
        if report is None:  # pragma: no cover - only if deleted mid-generation
            return {"report_id": str(report_id), "status": "failed"}

        store_report(
            db,
            report=report,
            document_id=payload.document_id,
            user_id=user_id,
            report_name=payload.report_name,
            classification=payload.classification,
            sections=result.sections,
            errors=result.errors,
            usage=result.usage,
            generation_ms=result.generation_ms,
            evidence=result.evidence,
            ungrounded_findings=result.ungrounded_findings,
            invalid_citations=result.invalid_citations,
        )

        user = db.get(models.Users, user_id)
        audit.record(
            db,
            action=audit.REPORT_CREATE,
            outcome=audit.SUCCESS if not result.sections.is_empty() else audit.FAILURE,
            request=request,
            actor=user,
            target_type="report",
            target_id=report.report_id,
            detail={
                "report_name": report.report_name,
                "document_id": str(payload.document_id),
                "classification": report.classification,
                "status": report.status,
                # The one field that differs from the non-streaming path. Both
                # write the same row through the same function; how it was
                # asked for is the only thing worth telling them apart by.
                "origin": "app-stream",
                "section_errors": len(result.errors),
                "cost_usd": report.total_cost_usd,
                "total_tokens": report.total_tokens,
                "ungrounded_findings": report.ungrounded_findings,
                "invalid_citations": report.invalid_citations,
            },
        )
        return {
            "report_id": str(report.report_id),
            "status": report.status,
            "generation_ms": result.generation_ms,
            "total_tokens": report.total_tokens,
            "cost_usd": report.total_cost_usd,
            "ungrounded_findings": report.ungrounded_findings,
            "invalid_citations": report.invalid_citations,
            "errors": [error.model_dump() for error in result.errors],
        }
    except Exception as exc:
        # A reserved row must never be left in `generating`: that is a state
        # meaning "still running" attached to something that is not.
        logger.exception("streamed generation failed", extra={"report_id": str(report_id)})
        report = db.get(models.Report, report_id)
        if report is not None:
            fail_report(db, report, f"generation failed: {exc}")
        return {"report_id": str(report_id), "status": "failed", "detail": str(exc)}
    finally:
        db.close()


async def stream_generation(
    *,
    report: models.Report,
    payload: GenerateReportRequest,
    user_id: uuid.UUID,
    request: Request,
) -> AsyncIterator[bytes]:
    """Yield SSE frames for one generation, in a guaranteed order.

    `started` first and exactly once, then per-section events, then exactly one
    terminal frame — `stored`. Anything reading this can rely on that: a client
    that has seen `stored` knows the report is written, and a client that has
    not knows only that it might be.
    """
    progress = _Progress()
    task = asyncio.create_task(
        _generate_and_store(
            progress, report_id=report.report_id, payload=payload, user_id=user_id,
            request=request,
        )
    )
    _running.add(task)
    task.add_done_callback(_running.discard)

    yield sse(
        "started",
        {
            "report_id": str(report.report_id),
            "document_id": str(payload.document_id),
            "report_name": report.report_name,
            # Named up front so the UI can render five pending rows instead of
            # growing the list as results arrive — a list that reflows on every
            # event is unreadable, and it hides how much is still outstanding.
            "sections": [spec.name for spec in SECTION_SPECS],
        },
    )

    while True:
        getter = asyncio.ensure_future(progress.queue.get())
        done, _ = await asyncio.wait(
            {getter, task},
            timeout=HEARTBEAT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if getter in done:
            yield sse("section", _event_payload(getter.result()))
            continue

        getter.cancel()
        if task in done:
            # Drain anything that landed between the last read and the task
            # finishing, so the last section's `completed` is never lost to the
            # race with the terminal frame.
            while not progress.queue.empty():
                yield sse("section", _event_payload(progress.queue.get_nowait()))
            yield sse("stored", task.result())
            return

        # Neither fired: the timeout did. A comment, not an event — clients
        # ignore it, and it is only here to keep the socket warm.
        yield b": heartbeat\n\n"
