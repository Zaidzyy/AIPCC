"""Turning tokens into money.

The price table is configuration (`settings.llm_prices`), not constants in this
module — prices change without notice and differ per account, so a number
compiled in here is a number nobody will remember to check. See
`core/config.ModelPrice`.

Two rules, and they are the same rule stated twice:

* **An unpriced model costs `None`, not `0`.** A model missing from the table
  means "nobody has told this system what it costs", which is not "free". Zero
  would quietly drag a dashboard total downwards and the figure would still
  look plausible, which is the worst kind of wrong number.
* **Unreported tokens cost `None`.** If a provider returned no usage there is
  nothing to multiply, and a `$0.00` next to a report that definitely cost
  something is a lie the UI would have no way to detect.

Ollama is the one genuine zero, and it is in the table explicitly rather than
by omission — free because it runs on your own hardware, with tokens still
counted so the "what would this have cost elsewhere" question stays answerable.
"""

from __future__ import annotations

from app.core.config import ModelPrice, settings
from app.services.llm.base import Usage

PER_MILLION = 1_000_000


def price_for(model: str) -> ModelPrice | None:
    """Look up a model's price, tolerating the prefixes providers add.

    Exact match first. Failing that, the longest configured key that the model
    name starts with — so `models/gemini-2.5-flash` and
    `gemini-2.5-flash-preview-09-2025` both resolve to the `gemini-2.5-flash`
    entry instead of silently costing nothing. Longest-first matters: with both
    `gemini-2.5-flash` and `gemini-2.5-flash-lite` configured, a shortest-match
    would price the lite model as the expensive one.
    """
    table = settings.llm_prices
    if model in table:
        return table[model]

    candidates = [key for key in table if model.startswith(key) or key in model]
    if not candidates:
        return None
    return table[max(candidates, key=len)]


def cost_of(model: str, usage: Usage) -> float | None:
    """USD for one call, or None when it cannot honestly be computed."""
    if not usage.reported:
        return None
    price = price_for(model)
    if price is None:
        return None

    prompt = usage.prompt_tokens or 0
    completion = usage.completion_tokens or 0
    return (
        prompt * price.input_usd_per_1m + completion * price.output_usd_per_1m
    ) / PER_MILLION
