"""Recording real provider responses, and replaying them deterministically.

**Why the CI gate replays instead of calling a model.** A quality gate that
makes live LLM calls on every push needs a secret in CI, costs money per push,
and is flaky by construction — the same prompt does not return the same text
twice. A flaky gate gets marked `continue-on-error` within a week and deleted
within a month, and then the project has a quality gate in name only. So CI
replays responses that were recorded once from a real provider, and a separate
opt-in `--live` run does the actual measuring.

**What replay proves, and what it does not.** It proves the *harness* is
correct: that the parser, the validators, the citation resolver, the golden
matcher and the metric arithmetic behave as claimed on known inputs, and that a
change to any of them moves the numbers. It does **not** prove anything about
the current model — those responses are frozen. `--live` is the only mode whose
numbers describe a model, and the run report labels every result with its mode
so the two can never be read as the same thing.

**Keying.** A fixture is keyed by the SHA-256 of the exact prompt. Change the
prompt — a new field, different guidance, a reworded instruction — and the key
changes, replay misses, and the run fails loudly telling you to re-record.
That is the desired behaviour: silently replaying a response to a *different*
prompt would report the old model's quality as if it were the new prompt's.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from app.services.llm.base import LLMError, LLMProvider, Usage

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CASSETTE = FIXTURE_DIR / "golden_run.json"


def prompt_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class FixtureMiss(LLMError):
    """No recorded response for this prompt."""


@dataclass
class Interaction:
    key: str
    section: str
    attempt: int
    prompt_preview: str
    response: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float


class RecordingProvider(LLMProvider):
    """Wraps a real provider and writes down everything it returns.

    **Recording is serialised and paced, and the application is not.** The five
    sections deliberately fan out concurrently — that is the whole point of
    Phase 1 and what Phase 9's trace proves — but firing five full log prompts
    at once is exactly what free provider tiers rate-limit on, by input tokens
    per minute. Recording that way failed repeatedly with `RESOURCE_EXHAUSTED`
    and produced cassettes missing two or three sections.

    A recorder that cannot record on the tier most people have is not much of a
    recorder, so this one takes a lock and waits between calls. It costs a
    minute on a command that is run rarely and by hand, and it changes nothing
    about how the application itself calls the provider.
    """

    def __init__(self, inner: LLMProvider, min_interval_seconds: float = 20.0):
        self._inner = inner
        self.name = inner.name
        self.model = inner.model
        self.interactions: list[Interaction] = []
        self._seen: dict[str, int] = {}
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        async with self._lock:
            if self._last_call is not None:
                wait = self._min_interval - (time.monotonic() - self._last_call)
                if wait > 0:
                    await asyncio.sleep(wait)
            result = await self._inner.generate(prompt)
            self._last_call = time.monotonic()

        key = prompt_key(prompt)
        self._seen[key] = self._seen.get(key, 0) + 1
        self.interactions.append(
            Interaction(
                key=key,
                section=_section_of(prompt),
                attempt=self._seen[key],
                # Enough of the prompt to recognise the fixture by eye when
                # reviewing the diff, and far too little to reconstruct it —
                # the key is the hash, not this.
                prompt_preview=prompt[:180].replace("\n", " "),
                response=result.text,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                latency_ms=result.latency_ms,
            )
        )
        return result.text, result.usage

    def save(self, path: Path = CASSETTE, *, note: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_about": {
                "recorded_from": f"{self.name}:{self.model}",
                "note": note
                or (
                    "Real responses from a live provider, recorded once. Replayed "
                    "by the CI gate so the gate is deterministic and needs no API "
                    "key. These do not track the current model — re-record with "
                    "`python -m app.eval.run --live --record`."
                ),
                "keying": "sha256 of the exact prompt; a prompt change invalidates the fixture",
                "interactions": len(self.interactions),
            },
            "interactions": [
                {
                    "key": item.key,
                    "section": item.section,
                    "attempt": item.attempt,
                    "prompt_preview": item.prompt_preview,
                    "prompt_tokens": item.prompt_tokens,
                    "completion_tokens": item.completion_tokens,
                    "latency_ms": item.latency_ms,
                    "response": item.response,
                }
                for item in self.interactions
            ],
        }
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return path


class ReplayProvider(LLMProvider):
    """Serves recorded responses. Never touches the network."""

    name = "replay"

    def __init__(self, path: Path = CASSETTE):
        if not path.exists():
            raise FixtureMiss(
                f"no recorded fixtures at {path}. Record them once with a real "
                "provider: python -m app.eval.run --live --record"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.model = payload["_about"]["recorded_from"].split(":", 1)[-1]
        self.recorded_from = payload["_about"]["recorded_from"]

        # Keyed by (prompt hash, attempt), because one prompt can legitimately
        # be issued twice — the repair retry re-prompts, and a section that was
        # retried must replay its *second* response the second time, not the
        # first one again, or the retry would appear to fix itself.
        self._responses: dict[tuple[str, int], str] = {}
        for item in payload["interactions"]:
            self._responses[(item["key"], item["attempt"])] = item["response"]
        self._served: dict[str, int] = {}
        self.misses: list[str] = []

    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        key = prompt_key(prompt)
        attempt = self._served.get(key, 0) + 1
        self._served[key] = attempt

        if (key, attempt) not in self._responses:
            self.misses.append(f"{_section_of(prompt)} attempt {attempt} ({key[:12]})")
            raise FixtureMiss(
                f"no recorded response for {_section_of(prompt)} attempt {attempt}. "
                "The prompt has changed since these fixtures were recorded — "
                "re-record with: python -m app.eval.run --live --record"
            )

        # No token counts: a replayed call did not spend anything, and
        # reporting the recorded numbers as though they were this run's would
        # make a replayed run look like it cost money. `None` is the truth, and
        # the cost columns render it as "not measured".
        return self._responses[(key, attempt)], Usage()


def _section_of(prompt: str) -> str:
    """Which section a prompt belongs to, read off its own JSON skeleton."""
    from app.services.report import SECTION_SPECS

    for spec in SECTION_SPECS:
        if f'"{spec.name}"' in prompt:
            return spec.name
    return "unknown"
