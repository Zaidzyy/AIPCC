"""LLM provider selection.

One story, chosen by `LLM_PROVIDER`. The prototype reassigned its
`CURRENT_LLM_MODEL` global five times in one module and silently ended on
whichever assignment came last, while its README advertised a different
provider entirely.
"""

from __future__ import annotations

from functools import cache

from app.core.config import settings
from app.services.llm.base import (
    LLMError,
    LLMProvider,
    LLMResult,
    Usage,
    extract_text,
)
from app.services.llm.pricing import cost_of, price_for
from app.services.llm.providers import PROVIDERS

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "Usage",
    "cost_of",
    "extract_text",
    "get_llm_provider",
    "price_for",
]


@cache
def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Return the configured provider, constructing it once per name."""
    selected = (name or settings.llm_provider).lower()
    try:
        provider_cls = PROVIDERS[selected]
    except KeyError:
        raise LLMError(
            f"Unknown LLM_PROVIDER {selected!r}. Valid: {', '.join(sorted(PROVIDERS))}"
        ) from None
    return provider_cls()
