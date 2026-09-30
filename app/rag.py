"""The three core RAG steps: rewrite the query → retrieve → build the prompt.

Deliberately plain functions rather than a LangChain chain or agent: every step's
input and output is visible, so debugging or swapping a step is straightforward.
"""

import asyncio
from functools import lru_cache
from itertools import chain

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.vectorstores import VectorStore
from pydantic import BaseModel

from app.config import settings

REWRITE_SYSTEM = """\
你負責把球迷口語描述的棒球情境，改寫成適合檢索中華職棒規則條文的查詢。

做法：
- 改用規則書的正式用語，例如：洋將→外國籍球員、挑戰→即時重播輔助判決、\
擋壘→妨礙跑壘、干擾守備→妨礙守備、假牽制→投手犯規、內野高飛球→內野飛球、\
打者→擊球員、跑者→跑壘員、死球→比賽停止球。
- 補上這個情境可能涉及的規則術語。
- 只輸出一行查詢文字，不要回答問題，不要解釋。"""

RAG_SYSTEM = """\
你是中華職棒（CPBL）的規則顧問，根據聯盟官方文件回答比賽判決與規章問題。

作答規則：
1. 只能根據「參考條文」作答。條文沒有涵蓋或不足以判斷時，直接說明找不到依據，\
不要用一般棒球知識補充。
2. 先用一兩句話給出結論（該怎麼判），再說明依據。
3. 每個論點後面標註出處編號，例如 [1] 或 [2][3]，編號對應參考條文的編號。
4. 《棒球規則》裡的【加註】是中職自己的規定，優先採用；\
【軟式註】以及標明業餘棒球的內容不適用於中職。
5. 不同條文的規定有出入時，把差異與各自出處都講清楚。
6. 使用繁體中文與純文字，不要使用 Markdown 語法。"""

PLAIN_SYSTEM = """\
你是中華職棒（CPBL）的規則顧問，回答比賽判決與規章問題。
先用一兩句話給出結論，再說明理由。使用繁體中文與純文字，不要使用 Markdown 語法。"""


class Source(BaseModel):
    index: int
    doc_title: str
    section: str
    title: str
    context: str
    page: int
    url: str
    score: float
    text: str


class Rewrite(BaseModel):
    query: str
    model: str | None


@lru_cache
def get_llm() -> BaseChatModel:
    return init_chat_model(settings.llm_model)


def model_name(message: BaseMessage) -> str | None:
    """The model that actually produced a message, as reported by the provider.

    This can differ from LLM_MODEL: a router such as openrouter/free picks a model per request.
    When streaming, providers usually report it only on the final chunk.
    """
    metadata = message.response_metadata
    return metadata.get("model_name") or metadata.get("model")


async def rewrite_query(llm: BaseChatModel, question: str) -> Rewrite:
    response = await llm.ainvoke([("system", REWRITE_SYSTEM), ("human", question)])
    return Rewrite(query=response.text.strip(), model=model_name(response))


async def retrieve(store: VectorStore, queries: list[str], k: int) -> list[Source]:
    """Fetch k results per query, keep the best score for a chunk hit by several queries, return the top k."""
    results = await asyncio.gather(*(store.asimilarity_search_with_score(query, k=k) for query in queries))
    best: dict[str, tuple[Document, float]] = {}
    for document, score in chain.from_iterable(results):
        key = document.metadata["_id"]
        if key not in best or score > best[key][1]:
            best[key] = (document, score)
    ranked = sorted(best.values(), key=lambda pair: pair[1], reverse=True)[:k]
    return [
        Source(
            index=index,
            doc_title=document.metadata["doc_title"],
            section=document.metadata["section"],
            title=document.metadata["title"],
            context=document.metadata["context"],
            page=document.metadata["page"],
            url=document.metadata["url"],
            score=score,
            text=document.page_content,
        )
        for index, (document, score) in enumerate(ranked, start=1)
    ]


def build_messages(question: str, sources: list[Source] | None) -> list[tuple[str, str]]:
    """sources=None means no RAG: the model answers from its own knowledge (the comparison baseline)."""
    if sources is None:
        return [("system", PLAIN_SYSTEM), ("human", question)]
    context = "\n\n".join(f"[{source.index}] {source.text}" for source in sources)
    return [("system", RAG_SYSTEM), ("human", f"參考條文：\n\n{context}\n\n問題：{question}")]
