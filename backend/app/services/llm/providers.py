"""Concrete LLM providers.

Each wraps a LangChain chat model. Imports are deferred into the constructors
so that installing only the package for the provider you actually use is
enough — running with LLM_PROVIDER=ollama does not require the Gemini SDK.

Each also knows where *its* provider hides token usage, and nothing above this
file does. Gemini reports under `usage_metadata`, Groq under `token_usage`,
Ollama as `prompt_eval_count` / `eval_count` — three shapes for one fact. They
are normalised to `Usage` here so `report.py` and the dashboard see one.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.llm.base import (
    LLMError,
    LLMProvider,
    Usage,
    extract_text,
    usage_from_message,
)


class GeminiProvider(LLMProvider):
    """Google Gemini. The default: runnable with a single API key."""

    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise LLMError(
                "GEMINI_API_KEY is not set. Set it, or choose another LLM_PROVIDER."
            )
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LLMError(
                "langchain-google-genai is not installed. "
                "pip install langchain-google-genai"
            ) from exc

        self.model = settings.gemini_model
        self._model = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=settings.llm_temperature,
        )

    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"gemini call failed: {exc}") from exc
        return extract_text(response.content), _usage(
            response,
            prompt_keys=("prompt_token_count", "input_tokens", "prompt_tokens"),
            completion_keys=(
                "candidates_token_count",
                "output_tokens",
                "completion_tokens",
            ),
        )


class GroqProvider(LLMProvider):
    """Groq. Also what the n8n orchestrator uses."""

    name = "groq"

    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise LLMError(
                "GROQ_API_KEY is not set. Set it, or choose another LLM_PROVIDER."
            )
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LLMError(
                "langchain-groq is not installed. pip install langchain-groq"
            ) from exc

        self.model = settings.groq_model
        self._model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=settings.llm_temperature,
        )

    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"groq call failed: {exc}") from exc
        return extract_text(response.content), _usage(
            response,
            prompt_keys=("prompt_tokens", "input_tokens"),
            completion_keys=("completion_tokens", "output_tokens"),
        )


class OllamaProvider(LLMProvider):
    """Local Ollama — the data-sovereignty option.

    Documented and supported, but not the deployed default: it needs a
    persistent host with the model resident in memory.
    """

    name = "ollama"

    def __init__(self) -> None:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LLMError(
                "langchain-ollama is not installed. pip install langchain-ollama"
            ) from exc

        self.model = settings.ollama_model
        self._model = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
        )

    async def _invoke(self, prompt: str) -> tuple[str, Usage]:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(
                f"ollama call failed (is {settings.ollama_base_url} reachable?): {exc}"
            ) from exc
        # Ollama counts "evaluations", not tokens by that name, and reports
        # them on the message metadata rather than in any usage object.
        return extract_text(response.content), _usage(
            response,
            prompt_keys=("prompt_eval_count",),
            completion_keys=("eval_count",),
        )


def _usage(
    response: Any,
    *,
    prompt_keys: tuple[str, ...],
    completion_keys: tuple[str, ...],
) -> Usage:
    return usage_from_message(
        response, prompt_keys=prompt_keys, completion_keys=completion_keys
    )


PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
}
