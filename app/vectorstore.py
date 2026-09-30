"""Embeddings and Qdrant."""

from functools import lru_cache

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore

from app.config import settings


class FastEmbedEmbeddings(Embeddings):
    """Adapt fastembed (ONNX, runs on local CPU) to LangChain's Embeddings interface.

    To use a hosted embedding such as OpenAI's, return a different object from get_embeddings().
    A different embedding model changes both vector size and semantic space, so re-ingest afterwards.
    """

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # Some models use different prefixes for queries and passages; fastembed applies them per model.
        return next(iter(self._model.query_embed(text))).tolist()


@lru_cache
def get_embeddings() -> Embeddings:
    return FastEmbedEmbeddings(settings.embedding_model, str(settings.data_dir / "models"))


@lru_cache
def get_store() -> QdrantVectorStore:
    return QdrantVectorStore.from_existing_collection(
        embedding=get_embeddings(),
        collection_name=settings.collection,
        url=settings.qdrant_url,
    )
