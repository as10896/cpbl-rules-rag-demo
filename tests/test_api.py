"""Run the whole API flow with a fake LLM and fake embeddings: no API key or Qdrant service needed."""

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_qdrant import QdrantVectorStore

from app.main import app, llm_dependency, store_dependency
from app.rag import MAX_CHUNKS_PER_ARTICLE, cap_per_article, fuse


def make_document(section: str, text: str) -> Document:
    metadata = {
        "doc": "league",
        "doc_title": "聯盟規章",
        "section": section,
        "title": "",
        "context": "第9章",
        "page": 1,
        "url": "https://example.com/league.pdf#page=1",
    }
    return Document(page_content=text, metadata=metadata)


@pytest.fixture
def client():
    store = QdrantVectorStore.from_documents(
        [make_document("第45條", "總教練得提出挑戰"), make_document("第37條", "延長賽至第 12 局")],
        DeterministicFakeEmbedding(size=32),
        location=":memory:",
        collection_name="test",
    )
    app.dependency_overrides[store_dependency] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


MODEL = {"model_name": "fake-model"}


class FakeChatModel(GenericFakeChatModel):
    """Like real providers when streaming, reports the model name on a final, empty chunk."""

    def _stream(self, *args, **kwargs):
        yield from super()._stream(*args, **kwargs)
        yield ChatGenerationChunk(message=AIMessageChunk(content="", response_metadata=MODEL))


def use_llm(*replies: str) -> None:
    llm = FakeChatModel(messages=iter(AIMessage(content=reply, response_metadata=MODEL) for reply in replies))
    app.dependency_overrides[llm_dependency] = lambda: llm


def read_events(response) -> list[tuple[str, object]]:
    events = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "data" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def make_hit(chunk_id: str, score: float) -> tuple[Document, float]:
    document = make_document("第45條", chunk_id)
    document.metadata["_id"] = chunk_id
    return document, score


def test_fusion_ranks_by_position_not_by_score():
    original = [make_hit("a", 0.60), make_hit("b", 0.55)]
    # A rewrite that went astray: unrelated chunks, all scoring higher than anything the original found.
    rewrite = [make_hit("x", 0.90), make_hit("b", 0.85), make_hit("y", 0.80)]
    fused = fuse([original, rewrite])
    # "b" is found by both queries so it leads; "a", the original's top hit, is not pushed out by "y".
    assert [document.page_content for document, _ in fused] == ["b", "a", "x", "y"]
    assert fused[0][1] == 0.85


def test_one_article_cannot_fill_every_slot():
    long_article = [(make_document("6.01", f"chunk {i}"), 0.9 - i / 100) for i in range(6)]
    other_article = (make_document("3.26", "本壘衝撞之規定"), 0.5)
    selected = cap_per_article([*long_article, other_article], k=6)
    sections = [document.metadata["section"] for document, _ in selected]
    assert sections == ["6.01"] * MAX_CHUNKS_PER_ARTICLE + ["3.26"]


def test_search_returns_ranked_sources(client):
    response = client.get("/api/search", params={"q": "總教練得提出挑戰", "k": 2})
    assert response.status_code == 200
    sources = response.json()
    assert [source["index"] for source in sources] == [1, 2]
    assert sources[0]["section"] == "第45條"


def test_chat_with_rag_streams_rewrite_sources_then_tokens(client):
    use_llm("即時重播輔助判決 挑戰次數", "可以挑戰 [1]")
    response = client.post("/api/chat", json={"question": "可以挑戰幾次？", "top_k": 2})
    events = read_events(response)
    assert [name for name, _ in events[:2]] == ["rewrite", "sources"]
    assert events[0][1] == {"query": "即時重播輔助判決 挑戰次數", "model": "fake-model"}
    assert len(events[1][1]) == 2
    assert "".join(data for name, data in events if name == "token") == "可以挑戰 [1]"
    assert [data for name, data in events if name == "model"] == ["fake-model"]


def test_chat_without_rag_only_streams_tokens(client):
    use_llm("憑印象回答")
    response = client.post("/api/chat", json={"question": "可以挑戰幾次？", "use_rag": False})
    assert {name for name, _ in read_events(response)} == {"token", "model"}


def test_chat_reports_llm_failure_as_error_event(client):
    use_llm()  # no replies queued, so the call raises
    response = client.post("/api/chat", json={"question": "可以挑戰幾次？", "use_rag": False})
    assert [name for name, _ in read_events(response)] == ["error"]


def test_frontend_is_served(client):
    assert "CPBL 規則 RAG" in client.get("/").text
