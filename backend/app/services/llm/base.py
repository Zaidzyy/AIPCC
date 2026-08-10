"""LLM provider interface.

The rest of the app depends on `LLMProvider.generate()` and nothing else — no
LangChain types leak past this package, so swapping the backing library later
touches only these files.

**This is the seam where usage is measured**, and it is the only correct place
for it. Every LLM call in the application goes through here — report sections,
their repair retries, and chat — so measuring here means the accounting cannot
miss a path somebody adds later, and every provider reports in the same shape.
Providers disagree about where usage lives (Gemini's `usage_metadata`, Groq's
`token_usage`, Ollama's `eval_count`); normalising in each subclass is what
keeps those three shapes from leaking upward into `report.py`.

**Unknown is null, never zero.** A provider that reports no usage yields
`prompt_tokens=None` and `cost_usd=None`. Substituting zero would put "this was
free" and "nobody measured it" in the same bucket, which is the one pair of
states this project refuses to conflate — the same rule as `UNKNOWN` integrity
and the dashboard's `—`.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Any

from app.core.tracing import get_tracer

tracer = get_tracer(__name__)


class LLMError(RuntimeError):
    """The provider failed to return a completion."""


@dataclass(frozen=True)
class Usage:
    """Token counts for one call. `None` means the provider did not say."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    @property
    def reported(self) -> bool:
        return self.prompt_tokens is not None or self.completion_tokens is not None


@dataclass(frozen=True)
class LLMResult:
    """One completion, plus what it cost to get it."""

    text: str
    provider: str
    model: str
    usage: Usage
    latency_ms: float
    cost_usd: float | None


class LLMProvider(abc.ABC):
    """Minimal contract: text in, text and measurement out."""

    name: str
    model: str

    @abc.abstractmethod
    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        """Call the model. Raise `LLMError` on failure."""

    async def generate(self, prompt: str) -> LLMResult:
        """Complete `prompt`, measuring latency, tokens and cost.

        Timing wraps `_invoke` rather than living in each subclass, so the
        three providers cannot measure three different things — and a fourth
        added later is measured without its author doing anything.
        """
        from app.services.llm.pricing import cost_of

        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.provider", self.name)
            span.set_attribute("llm.model", self.model)
            started = time.perf_counter()
            try:
                text, usage = await self._invoke(prompt)
            except LLMError:
                # The elapsed time is recorded on the span, but no usage row is
                # written for a call that never reached the model: a failed
                # request has no tokens, and inventing zeros for it would drag
                # every average down with calls that never happened.
                span.set_attribute("llm.failed", True)
                span.set_attribute(
                    "llm.latency_ms", round((time.perf_counter() - started) * 1000, 2)
                )
                raise

            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            cost = cost_of(self.model, usage)

            span.set_attribute("llm.latency_ms", latency_ms)
            if usage.prompt_tokens is not None:
                span.set_attribute("llm.prompt_tokens", usage.prompt_tokens)
            if usage.completion_tokens is not None:
                span.set_attribute("llm.completion_tokens", usage.completion_tokens)
            if cost is not None:
                span.set_attribute("llm.cost_usd", cost)
            # Deliberately absent from every span above: the prompt and the
            # completion. A trace is shipped to a collector; log data is not.

            return LLMResult(
                text=text,
                provider=self.name,
                model=self.model,
                usage=usage,
                latency_ms=latency_ms,
                cost_usd=cost,
            )

    async def complete(self, prompt: str) -> str:
        """Just the text. Kept for callers that do not account for usage."""
        return (await self.generate(prompt)).text


def extract_text(content: Any) -> str:
    """Normalize a chat model's `.content` into a plain string.

    Providers disagree on shape: most return a string, but some return a list
    of content blocks. The prototype assumed `content[0]["text"]`
    unconditionally, which raised a TypeError on every provider that returns a
    plain string — and that exception was swallowed into a silent error dict.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    if content is None:
        raise LLMError("provider returned empty content")
    return str(content)


def _first_int(source: Any, *keys: str) -> int | None:
    """Read the first present integer among `keys` from a dict-ish object."""
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def usage_from_message(
    response: Any,
    *,
    prompt_keys: tuple[str, ...],
    completion_keys: tuple[str, ...],
) -> Usage:
    """Pull token counts out of a LangChain message, provider shape by provider shape.

    Three places are tried in order, because which one is populated depends on
    the provider *and* on the version of its LangChain package:

    1. `usage_metadata` — LangChain's own normalised field, present on newer
       integrations and by far the most reliable when it exists;
    2. `response_metadata[...]` under the provider's own key, which is where
       Groq's `token_usage` and Gemini's `usage_metadata` actually land;
    3. the provider-specific top-level keys passed in by the caller — Ollama
       reports `prompt_eval_count` / `eval_count` and nothing else.

    Anything not found stays `None`. This function never estimates: a token
    count this system did not receive is not a number it should invent, because
    it is multiplied by a price and presented as money.
    """
    normalised = getattr(response, "usage_metadata", None)
    prompt = _first_int(normalised, "input_tokens", "prompt_tokens")
    completion = _first_int(normalised, "output_tokens", "completion_tokens")

    metadata = getattr(response, "response_metadata", None) or {}
    for container in (metadata.get("token_usage"), metadata.get("usage_metadata"), metadata):
        if prompt is None:
            prompt = _first_int(container, *prompt_keys)
        if completion is None:
            completion = _first_int(container, *completion_keys)

    return Usage(prompt_tokens=prompt, completion_tokens=completion)
