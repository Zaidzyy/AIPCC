"""Concrete LLM providers.

Each wraps a LangChain chat model. Imports are deferred into the constructors
so that installing only the package for the provider you actually use is
enough — running with LLM_PROVIDER=ollama does not require the Gemini SDK.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, extract_text


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

        self._model = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=settings.llm_temperature,
        )

    async def complete(self, prompt: str) -> str:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"gemini call failed: {exc}") from exc
        return extract_text(response.content)


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

        self._model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=settings.llm_temperature,
        )

    async def complete(self, prompt: str) -> str:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"groq call failed: {exc}") from exc
        return extract_text(response.content)


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

        self._model = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
        )

    async def complete(self, prompt: str) -> str:
        try:
            response = await self._model.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(
                f"ollama call failed (is {settings.ollama_base_url} reachable?): {exc}"
            ) from exc
        return extract_text(response.content)


PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
}
