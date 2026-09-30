# CPBL Rules RAG

[![English](https://img.shields.io/badge/English-read-brightgreen)](README.md)
[![繁體中文](https://img.shields.io/badge/%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-read-blue)](README_zh-TW.md)

A RAG example that uses the official rule documents of the CPBL (Chinese Professional Baseball League, Taiwan) as its knowledge base. Describe a game situation or ask a regulation question; the system retrieves the relevant articles and answers with the article number, page number and a link to the official PDF.

Stack: FastAPI, LangChain (component layer only), Qdrant and fastembed (local embeddings), all running under Docker Compose.

The corpus, the prompts and the web UI are in Traditional Chinese, so questions should be asked in Chinese.

## Quick start

```bash
cp .env.example .env          # fill in OPENROUTER_API_KEY (a free model is the default; other providers work too)
docker compose up -d --build
docker compose run --rm api python -m app.ingest   # download the PDFs and build the index, about 2 minutes
```

- Web UI: http://localhost:8000
- API docs: http://localhost:8000/docs
- Qdrant dashboard: http://localhost:6333/dashboard

For development, run `docker compose up --watch`; changes under `app/` or `frontend/` are synced into the container.

## Corpus

All three documents come from the [official CPBL site](https://www.cpbl.com.tw/). `ingest` downloads them into `data/`:

| Document | Content | Split unit |
|---|---|---|
| 棒球規則 (Official Baseball Rules, 2026) | The playing rules and the definitions of terms | Rule number (`5.07`), definition entry (`INFIELD FLY`) |
| 裁判執法手冊規則補述 (Umpire Manual Rule Supplement) | The league's interpretations of how rules apply to specific situations | Item number (`3.26`) |
| 聯盟規章 (League Regulations, 2026) | Competition rules, player registration, penalties and so on | Article (`第45條`) |

The documents are copyrighted by the CPBL and marked as not for reproduction, so `data/` is kept out of version control. When the league publishes a new edition, run `python -m app.ingest --refresh`. If the download fails, the site has most likely changed a file URL; update it in `app/corpus.py`.

## How it works

```
Indexing (app/ingest.py)
  PDF ─→ extract text per page, drop page numbers and running headers
      ─→ group into articles by article number ─→ split over-long articles into chunks
      ─→ prepend a citation header to each chunk ─→ embed ─→ Qdrant

Question answering (POST /api/chat, streamed as SSE)
  question ─→ LLM rewrites it in rulebook terminology
           ─→ retrieve once for the original and once for the rewrite, merge, keep the top k
           ─→ number the chunks and put them in the prompt
           ─→ LLM streams the answer, citing sources as [1][2]
```

## Code tour

| File | Responsibility |
|---|---|
| `app/corpus.py` | URLs and layout rules for the three documents (regexes for page numbers, running headers and article numbers), plus downloading |
| `app/parsing.py` | Text cleaning and splitting; pure functions only |
| `app/vectorstore.py` | The LangChain adapter for fastembed, and the Qdrant connection |
| `app/ingest.py` | The indexing command |
| `app/rag.py` | Prompts, query rewriting, retrieval and merging |
| `app/main.py` | FastAPI endpoints |
| `frontend/index.html` | Single-page UI with no build step |

## API

| Endpoint | Description |
|---|---|
| `GET /api/search?q=&k=` | Retrieval only; returns chunks with similarity scores. Use it to see the effect of changing the chunking or the embedding model |
| `POST /api/chat` | Takes `{question, use_rag, rewrite, top_k}` and streams `rewrite`, `sources`, `token` and `error` events as SSE |

```bash
curl --get localhost:8000/api/search --data-urlencode "q=延長賽最多打幾局" | jq '.[] | {section, title, score}'
```

## Design decisions

**Split by article number, not by fixed length.** The article is the semantic unit of a rule document, and citations need the article number. `RecursiveCharacterTextSplitter` is applied only when a single article exceeds `CHUNK_SIZE`.

**Every chunk starts with its citation**, for example `《棒球規則》5.09 出局｜5.09(b) 跑壘員出局`. Once a long article is split, the later chunks no longer show which article they belong to. Chapter 6 of the supplement is the clearest case: it lists the rulings that can be changed and the rulings that cannot, and without the header the items of the two lists are indistinguishable.

**Rewrite the query before retrieving.** Fans say 洋將 (foreign player), 挑戰 (challenge) and 擋壘 (blocking the base); the rulebook says 外國籍球員, 即時重播輔助判決 and 妨礙跑壘. To see the difference, untick 檢索前先改寫查詢 ("rewrite the query before retrieving") in the UI and ask 「洋將一場比賽最多可以同時上幾個？」 (how many foreign players can be on the field at once).

**LangChain components, but not its chains or agents.** The chat model, embeddings, vector store and text splitter all go through LangChain interfaces, so switching provider or vector database is a change in one place. The flow itself is three plain functions in `app/rag.py`, so what each step sends is always visible.

**The LLM and the vector store are injected as FastAPI dependencies.** Tests replace them through `dependency_overrides` with a fake LLM and an in-memory Qdrant, so the whole flow runs without an API key or any external service.

## Swapping components

- **LLM**: change `LLM_MODEL` in `.env` (format `provider:model`) and supply that provider's API key. The packages for Anthropic, OpenAI, OpenRouter and NVIDIA are installed; see `.env.example` for the settings. For a free option, use OpenRouter. The free tier of the NVIDIA API Catalog took minutes to respond when tested and times out, so it is not recommended. The next section covers adding other providers.
- **Embedding model**: change `EMBEDDING_MODEL`, then re-run ingest. The default `BAAI/bge-small-zh-v1.5` is small and fast. `jinaai/jina-embeddings-v2-base-zh` accepts longer input but takes about 7 times as long to index.
- **Vector database**: replace `get_store()` in `app/vectorstore.py` and the write call in `app/ingest.py`.

## Adding a new LLM provider

The LLM is created in exactly one place: `get_llm()` in `app/rag.py`, which hands `LLM_MODEL` to LangChain's `init_chat_model`. Most providers therefore need no code change, only a package and some environment variables.

### The usual case: a provider LangChain supports

The steps below use Groq as the example; substitute the name for any other provider.

1. **Confirm the provider name and its package.** The providers `init_chat_model` supports are listed in the [LangChain docs](https://docs.langchain.com/oss/python/integrations/providers/overview), each with a matching `langchain-<provider>` package. If the name is mistyped, the error message also lists every supported provider.

2. **Install the package.**

   ```bash
   uv add langchain-groq
   ```

   This updates `pyproject.toml` and `uv.lock`. A new package can shift the versions of other dependencies, so run `uv run pytest` afterwards to confirm nothing broke.

3. **Configure `.env`.** The name of the API key variable depends on the package. It is usually `<PROVIDER>_API_KEY`; check that package's documentation.

   ```bash
   LLM_MODEL=groq:<model id>
   GROQ_API_KEY=...
   ```

   `LLM_MODEL` is split into provider and model at the first colon only, so a model id that itself contains `/` or `:` is fine, for example `openrouter:vendor/model:free`.

   `compose.yaml` passes the whole `.env` file into the container, so new variables need no change there.

4. **Rebuild and verify.**

   ```bash
   docker compose up -d --build
   docker compose exec api python -c "from app.rag import get_llm; print(get_llm().invoke('用繁體中文說你好').text)"
   ```

   The second command skips retrieval and checks the key, the model name and the connection directly. It also shows how long a response takes.

5. **Add an example to `.env.example`**, noting whether the provider is paid and how fast it was when tested, so the reason for choosing or avoiding it is on record.

### OpenAI-compatible endpoints

A self-hosted inference server (vLLM, LM Studio and the like), or a service that only offers an OpenAI-compatible API, needs no new package. Keep the `openai` provider and override the endpoint URL:

```bash
LLM_MODEL=openai:<model id>
OPENAI_API_BASE=https://your-endpoint/v1
OPENAI_API_KEY=...
```

### When extra parameters are needed

`init_chat_model` accepts extra keyword arguments and forwards them to the underlying chat model class. To pin `temperature`, set a `timeout` or specify a `base_url`, change `get_llm()`:

```python
@lru_cache
def get_llm() -> BaseChatModel:
    return init_chat_model(settings.llm_model, timeout=120)
```

Providers do not all accept the same parameters, so test every provider you use after adding one. If a parameter should vary by environment, add a field to `Settings` in `app/config.py` and pass it in.

### A provider LangChain does not support

Write a class that inherits from `BaseChatModel` (implement `_generate` at minimum, and `_astream` for streaming) and return it from `get_llm()`. `FastEmbedEmbeddings` in `app/vectorstore.py` is an example of the same approach applied to embeddings. The rest of the code depends only on the `BaseChatModel` interface and needs no change.

### What to check after switching provider

The project asks three things of an LLM. Confirm each of them with a new provider:

- **Streaming**: `/api/chat` uses `astream()`. A model without streaming still works, but the answer appears all at once.
- **Response time**: one question sends 2 to 3 requests (query rewrite, RAG answer, no-RAG answer). A service that takes minutes per request will time out, which is what happens on NVIDIA's free tier.
- **Following instructions**: smaller models may omit the `[1]` citations, answer in Simplified Chinese, or add explanations when rewriting the query. Trying a few of the sample questions in the UI tells you more than a spec sheet.

The tests (`uv run pytest`) use a fake LLM. They will not fail because of a provider change, and for the same reason they cannot verify the three points above.

## Tests

```bash
uv run pytest
```

`tests/test_parsing.py` checks the splitting rules against short sample text. `tests/test_api.py` runs the full API flow with a fake LLM.

## Known limitations and possible extensions

- **Vector search only.** Looking up an article by its number ("what does 5.09(b)(7) say") works poorly. Hybrid search with Qdrant sparse vectors would help. Chinese text needs word segmentation first (jieba, for example), because fastembed's built-in BM25 does not segment Chinese.
- **No reranker.** Results are ordered by similarity alone. Reranking the top 20 with a cross-encoder usually improves the accuracy of the first few results.
- **Images are not processed.** The field diagrams in the rules and the illustrations in the supplement are not indexed.
- **Cross-references are not followed.** Articles often say "see 6.01(a)"; the referenced article is not fetched along with them.
- **No evaluation set.** Comparing chunking strategies or embedding models systematically needs a list of questions with the articles each should retrieve, to compute recall@k.
- **Single-turn only.** There is no conversation memory; every question is handled independently.
- **Answers are only as current as the published PDFs.** The supplement on the official site is the 2024 edition, so a rule the league has changed since then (the pitch timer, for example) is answered according to the older text.
