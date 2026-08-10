"""Phase 3 tests: chat over ingested documents.

Two layers. `TestChatbotService` exercises the pure functions with no database
and no vector store — which is only possible because `services/chatbot.py`
takes plain values, unlike the prototype's version that opened a session and
called the LLM in the same function. `TestChatEndpoints` covers the routes:
happy path plus auth rejection for each, per CLAUDE.md > Conventions.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.chatbot import (
    ChatTurn,
    RetrievedChunk,
    answer,
    build_prompt,
    derive_chat_name,
    retrieve_chunks,
)
from app.services.llm.base import LLMError, LLMProvider


class FakeProvider(LLMProvider):
    """Returns one canned response; records the prompt it saw."""

    name = "fake"

    def __init__(self, response: str | Exception = "An answer."):
        self._response = response
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _StubHit:
    def __init__(self, content: str):
        self.page_content = content


class _StubStore:
    """Stands in for Chroma; records the filters it was asked for."""

    def __init__(self, hits_by_document: dict[str, list[str]]):
        self.hits_by_document = hits_by_document
        self.filters: list[dict] = []

    def similarity_search(self, query, k, filter):
        self.filters.append(filter)
        return [_StubHit(c) for c in self.hits_by_document.get(filter["document_id"], [])]


# --- Service layer --------------------------------------------------------


class TestChatbotService:
    def test_retrieval_is_scoped_per_document(self, monkeypatch):
        doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
        store = _StubStore({str(doc_a): ["chunk a"], str(doc_b): ["chunk b"]})
        monkeypatch.setattr(
            "app.services.rag.vectorstore.get_vectorstore", lambda: store
        )

        chunks = retrieve_chunks(
            "what happened", [(doc_a, "a.csv"), (doc_b, "b.log")]
        )

        assert [c.content for c in chunks] == ["chunk a", "chunk b"]
        # Each hit carries the document it came from, so the answer can cite it.
        assert [c.document_name for c in chunks] == ["a.csv", "b.log"]
        assert store.filters == [
            {"document_id": str(doc_a)},
            {"document_id": str(doc_b)},
        ]

    def test_no_attached_documents_retrieves_nothing(self, monkeypatch):
        def explode():  # pragma: no cover - must never be reached
            raise AssertionError("the vector store should not be opened")

        monkeypatch.setattr("app.services.rag.vectorstore.get_vectorstore", explode)
        assert retrieve_chunks("anything", []) == []

    def test_duplicate_chunks_are_dropped(self, monkeypatch):
        doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
        store = _StubStore({str(doc_a): ["same"], str(doc_b): ["same"]})
        monkeypatch.setattr(
            "app.services.rag.vectorstore.get_vectorstore", lambda: store
        )
        chunks = retrieve_chunks("q", [(doc_a, "a.csv"), (doc_b, "b.csv")])
        assert len(chunks) == 1

    def test_prompt_carries_context_history_and_question(self):
        prompt = build_prompt(
            "who logged in?",
            [RetrievedChunk(uuid.uuid4(), "auth.log", "root login from 10.0.0.1")],
            [ChatTurn("human", "hello"), ChatTurn("assistant", "hi")],
        )
        assert "root login from 10.0.0.1" in prompt
        assert "from 'auth.log'" in prompt
        assert "User: hello" in prompt
        assert "Assistant: hi" in prompt
        assert "who logged in?" in prompt

    def test_prompt_says_so_when_nothing_is_attached(self):
        prompt = build_prompt("hi", [], [])
        assert "no documents are attached" in prompt
        assert "this is the first message" in prompt

    def test_history_is_capped(self):
        turns = [ChatTurn("human", f"message {i}") for i in range(40)]
        prompt = build_prompt("now what", [], turns)
        assert "message 39" in prompt
        assert "message 0" not in prompt

    def test_answer_returns_reply_and_sources(self, monkeypatch):
        document_id = uuid.uuid4()
        store = _StubStore({str(document_id): ["suspicious chunk"]})
        monkeypatch.setattr(
            "app.services.rag.vectorstore.get_vectorstore", lambda: store
        )
        provider = FakeProvider("  Three failed logins.  ")

        reply, chunks = asyncio.run(
            answer("what happened", [(document_id, "auth.log")], [], provider)
        )

        assert reply == "Three failed logins."
        assert [c.content for c in chunks] == ["suspicious chunk"]
        assert "suspicious chunk" in provider.prompts[0]

    def test_provider_failure_propagates(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.rag.vectorstore.get_vectorstore",
            lambda: _StubStore({}),
        )
        with pytest.raises(LLMError):
            asyncio.run(
                answer("q", [], [], FakeProvider(LLMError("api key rejected")))
            )

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("Why did the firewall drop that?", "Why did the firewall drop that?"),
            ("   ", "New chat"),
            ("a" * 80, "a" * 59 + "…"),
        ],
    )
    def test_chat_name_is_derived_locally(self, message, expected):
        # Deliberately not an LLM call: naming a chat must not be able to fail.
        assert derive_chat_name(message) == expected


# --- Endpoints ------------------------------------------------------------


@pytest.fixture
def fake_answer(monkeypatch):
    """Replace the service call so route tests need no LLM and no Chroma."""
    calls: list[tuple] = []

    async def _answer(question, documents, history, provider=None):
        calls.append((question, documents, history))
        return "A grounded answer.", [
            RetrievedChunk(doc_id, name, "matched log line")
            for doc_id, name in documents
        ]

    monkeypatch.setattr("app.api.routers.chat.answer", _answer)
    return calls


@pytest.fixture
def chat_id(api, analyst_auth, document) -> str:
    response = api.post(
        "/chats",
        json={"document_ids": [str(document.document_id)]},
        headers=analyst_auth,
    )
    assert response.status_code == 201, response.text
    return response.json()["chat_id"]


class TestChatEndpoints:
    def test_create_chat_attaches_owned_document(self, api, analyst_auth, document):
        response = api.post(
            "/chats",
            json={"document_ids": [str(document.document_id)]},
            headers=analyst_auth,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["chat_name"] == "New chat"
        assert body["messages"] == []
        assert body["attached_documents"] == [
            {
                "document_id": str(document.document_id),
                "document_name": document.document_name,
            }
        ]

    def test_create_chat_requires_auth(self, api):
        assert api.post("/chats", json={}).status_code == 401

    def test_cannot_attach_someone_elses_document(self, api, other_auth, document):
        # 404, not 403 — see deps.authorize_owner.
        response = api.post(
            "/chats",
            json={"document_ids": [str(document.document_id)]},
            headers=other_auth,
        )
        assert response.status_code == 404

    def test_list_chats_is_scoped_to_the_caller(
        self, api, analyst_auth, other_auth, chat_id
    ):
        mine = api.get("/chats", headers=analyst_auth).json()
        assert [c["chat_id"] for c in mine] == [chat_id]
        assert api.get("/chats", headers=other_auth).json() == []

    def test_list_chats_requires_auth(self, api):
        assert api.get("/chats").status_code == 401

    def test_send_message_persists_both_sides(
        self, api, analyst_auth, chat_id, document, fake_answer
    ):
        response = api.post(
            f"/chats/{chat_id}/messages",
            json={"message": "What attacks are in this log?"},
            headers=analyst_auth,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_message"]["role"] == "human"
        assert body["user_message"]["context"] == "What attacks are in this log?"
        assert body["assistant_message"]["role"] == "assistant"
        assert body["assistant_message"]["context"] == "A grounded answer."
        assert body["sources"] == [
            {
                "document_id": str(document.document_id),
                "document_name": document.document_name,
                "excerpt": "matched log line",
            }
        ]

        # And they are readable back, in order.
        transcript = api.get(f"/chats/{chat_id}", headers=analyst_auth).json()
        assert [m["role"] for m in transcript["messages"]] == ["human", "assistant"]

    def test_first_message_names_the_chat(
        self, api, analyst_auth, chat_id, fake_answer
    ):
        api.post(
            f"/chats/{chat_id}/messages",
            json={"message": "Explain the brute force attempts"},
            headers=analyst_auth,
        )
        detail = api.get(f"/chats/{chat_id}", headers=analyst_auth).json()
        assert detail["chat_name"] == "Explain the brute force attempts"

    def test_history_is_passed_to_the_service(
        self, api, analyst_auth, chat_id, fake_answer
    ):
        api.post(
            f"/chats/{chat_id}/messages", json={"message": "first"}, headers=analyst_auth
        )
        api.post(
            f"/chats/{chat_id}/messages", json={"message": "second"}, headers=analyst_auth
        )
        _, _, history = fake_answer[-1]
        assert [turn.context for turn in history] == ["first", "A grounded answer."]

    def test_provider_outage_keeps_the_question(
        self, api, analyst_auth, chat_id, monkeypatch
    ):
        async def _fail(question, documents, history, provider=None):
            raise LLMError("api key rejected")

        monkeypatch.setattr("app.api.routers.chat.answer", _fail)

        response = api.post(
            f"/chats/{chat_id}/messages",
            json={"message": "will this survive?"},
            headers=analyst_auth,
        )
        assert response.status_code == 502
        assert "unavailable" in response.json()["detail"]

        # The prototype lost the question along with the answer.
        detail = api.get(f"/chats/{chat_id}", headers=analyst_auth).json()
        assert [m["context"] for m in detail["messages"]] == ["will this survive?"]
        assert detail["messages"][0]["status"] == "failed"

    def test_send_message_requires_auth(self, api, chat_id):
        response = api.post(f"/chats/{chat_id}/messages", json={"message": "hi"})
        assert response.status_code == 401

    def test_empty_message_is_rejected(self, api, analyst_auth, chat_id):
        response = api.post(
            f"/chats/{chat_id}/messages", json={"message": ""}, headers=analyst_auth
        )
        assert response.status_code == 422

    def test_cannot_read_someone_elses_chat(self, api, other_auth, chat_id):
        assert api.get(f"/chats/{chat_id}", headers=other_auth).status_code == 404

    def test_admin_can_read_any_chat(self, api, admin_auth, chat_id):
        assert api.get(f"/chats/{chat_id}", headers=admin_auth).status_code == 200

    def test_delete_chat(self, api, analyst_auth, chat_id):
        assert api.delete(f"/chats/{chat_id}", headers=analyst_auth).status_code == 204
        assert api.get(f"/chats/{chat_id}", headers=analyst_auth).status_code == 404

    def test_delete_chat_requires_auth(self, api, chat_id):
        assert api.delete(f"/chats/{chat_id}").status_code == 401

    def test_cannot_delete_someone_elses_chat(self, api, other_auth, chat_id):
        assert api.delete(f"/chats/{chat_id}", headers=other_auth).status_code == 404

    def test_unknown_chat_is_404(self, api, analyst_auth):
        response = api.get(f"/chats/{uuid.uuid4()}", headers=analyst_auth)
        assert response.status_code == 404
