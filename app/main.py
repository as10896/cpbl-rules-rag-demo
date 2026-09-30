import logging
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from pydantic import BaseModel, Field

from app.config import settings
from app.rag import Source, build_messages, get_llm, model_name, retrieve, rewrite_query
from app.vectorstore import get_store

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="CPBL 規則 RAG")


def llm_dependency() -> BaseChatModel:
    try:
        return get_llm()
    except Exception as error:
        raise HTTPException(503, f"無法建立 LLM（{settings.llm_model}），請檢查 .env 的 API key：{error}") from error


def store_dependency() -> VectorStore:
    try:
        return get_store()
    except Exception as error:
        raise HTTPException(
            503, f"向量資料庫尚未就緒，請先執行 docker compose run --rm api python -m app.ingest：{error}"
        ) from error


LLMDep = Annotated[BaseChatModel, Depends(llm_dependency)]
StoreDep = Annotated[VectorStore, Depends(store_dependency)]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    use_rag: bool = True
    rewrite: bool = True
    top_k: int = Field(default=6, ge=1, le=20)


@app.get("/api/search")
async def search(
    store: StoreDep,
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    k: Annotated[int, Query(ge=1, le=20)] = 6,
) -> list[Source]:
    """Retrieval only, no LLM call: for inspecting retrieval quality on its own."""
    return await retrieve(store, [q], k)


@app.post("/api/chat", response_class=EventSourceResponse)
async def chat(request: ChatRequest, llm: LLMDep, store: StoreDep) -> AsyncIterable[ServerSentEvent]:
    """Stream the response as SSE.

    Events, in order: rewrite (the rewritten query and the model that wrote it), sources (retrieved chunks),
    token (answer fragments), model (the model that answered).
    """
    try:
        sources = None
        if request.use_rag:
            queries = [request.question]
            if request.rewrite:
                rewritten = await rewrite_query(llm, request.question)
                queries.append(rewritten.query)
                yield ServerSentEvent(event="rewrite", data=rewritten)
            sources = await retrieve(store, queries, request.top_k)
            yield ServerSentEvent(event="sources", data=sources)
        answered_by = None
        async for chunk in llm.astream(build_messages(request.question, sources)):
            if chunk.text:
                yield ServerSentEvent(event="token", data=chunk.text)
            if not answered_by and (answered_by := model_name(chunk)):
                yield ServerSentEvent(event="model", data=answered_by)
    except Exception as error:
        # The 200 status is already sent once streaming starts, so errors can only reach the client as an event.
        logger.exception("chat failed")
        yield ServerSentEvent(event="error", data=str(error))


app.frontend("/", directory=Path(__file__).parent.parent / "frontend")
