"""LLM provider interface.

The rest of the app depends on `LLMProvider.complete()` and nothing else — no
LangChain types leak past this package, so swapping the backing library later
touches only these files.
"""

from __future__ import annotations

import abc
from typing import Any


class LLMError(RuntimeError):
    """The provider failed to return a completion."""


class LLMProvider(abc.ABC):
    """Minimal contract: text in, text out."""

    name: str

    @abc.abstractmethod
    async def complete(self, prompt: str) -> str:
        """Return the model's text response to `prompt`."""


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
