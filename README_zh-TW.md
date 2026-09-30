# CPBL 規則 RAG

[![English](https://img.shields.io/badge/English-read-brightgreen)](README.md)
[![繁體中文](https://img.shields.io/badge/%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-read-blue)](README_zh-TW.md)

以中華職棒官方規則文件為知識庫的 RAG 範例：描述一個比賽情境或規章問題，系統檢索相關條文後回答，並附上條號、頁碼與官方 PDF 連結。

技術組成：FastAPI、LangChain（元件層）、Qdrant、fastembed（本機 embedding），全部以 Docker Compose 執行。

## 快速開始

```bash
cp .env.example .env          # 填入 OPENROUTER_API_KEY（預設使用免費模型，或改用其他 provider）
docker compose up -d --build
docker compose run --rm api python -m app.ingest   # 下載 PDF 並建立索引，約 2 分鐘
```

- 問答介面：http://localhost:8000
- API 文件：http://localhost:8000/docs
- Qdrant 管理介面：http://localhost:6333/dashboard

開發時用 `docker compose up --watch`，修改 `app/` 或 `frontend/` 會自動同步進 container。

## 語料

三份文件都來自[中職官網](https://www.cpbl.com.tw/)，由 `ingest` 自動下載到 `data/`：

| 文件 | 內容 | 切分單位 |
|---|---|---|
| 棒球規則（2026） | 比賽規則本文與用語定義 | 條號（`5.07`）、定義詞條（`INFIELD FLY`） |
| 裁判執法手冊規則補述 | 中職對各種情境的執法解釋 | 條號（`3.26`） |
| 聯盟規章（2026） | 競賽規程、球員註冊、懲處等 | 條（`第45條`） |

文件著作權屬中華職業棒球大聯盟，並註明禁止複製轉載，所以 `data/` 不進版控。官方換新版時執行 `python -m app.ingest --refresh`；若下載失敗，通常是官網換了檔案網址，到 `app/corpus.py` 更新。

## 流程

```
建立索引（app/ingest.py）
  PDF ─→ 逐頁抽文字、去頁碼頁眉 ─→ 依條號分成條文 ─→ 過長的條文再切 chunk
      ─→ 每個 chunk 開頭加上出處標題 ─→ embedding ─→ Qdrant

問答（POST /api/chat，SSE 串流）
  問題 ─→ LLM 改寫成規則用語 ─→ 原問題與改寫後各檢索一次，合併取前 k 筆
      ─→ 條文編號後放進 prompt ─→ LLM 串流回答，以 [1][2] 標註出處
```

## 程式碼導覽

| 檔案 | 職責 |
|---|---|
| `app/corpus.py` | 三份文件的網址與版面規則（頁碼、頁眉、條號的正規表示式），以及下載 |
| `app/parsing.py` | 文字清理與切分，全部是純函式 |
| `app/vectorstore.py` | fastembed 的 LangChain 轉接層、Qdrant 連線 |
| `app/ingest.py` | 建立索引的指令 |
| `app/rag.py` | prompt、查詢改寫、檢索與合併 |
| `app/main.py` | FastAPI 端點 |
| `frontend/index.html` | 單頁介面，無建置步驟 |

## API

| 端點 | 說明 |
|---|---|
| `GET /api/search?q=&k=` | 只做檢索，回傳 chunk 與相似度。調整切分或 embedding 時用它觀察效果 |
| `POST /api/chat` | `{question, use_rag, rewrite, top_k}`，以 SSE 回傳 `rewrite`、`sources`、`token`、`error` 事件 |

```bash
curl --get localhost:8000/api/search --data-urlencode "q=延長賽最多打幾局" | jq '.[] | {section, title, score}'
```

## 設計決策

**依條號切分，而不是固定長度。** 規則文件的語意單位就是「條」，而且引用出處時需要條號。只有單一條文超過 `CHUNK_SIZE` 時才用 `RecursiveCharacterTextSplitter` 再切。

**每個 chunk 開頭都寫上出處**，例如 `《棒球規則》5.09 出局｜5.09(b) 跑壘員出局`。長條文被切成多塊後，後面的 chunk 本身看不出屬於哪一條；補述第六章的「可更改／不可更改判決」清單就是例子，少了標題，兩份清單的內容會無法區分。

**檢索前先改寫查詢。** 球迷說「洋將」「挑戰」「擋壘」，條文寫的是「外國籍球員」「即時重播輔助判決」「妨礙跑壘」。在介面上取消勾選「檢索前先改寫查詢」，用「洋將一場比賽最多可以同時上幾個？」就能看到差別。

**用 LangChain 的元件，不用它的 chain 或 agent。** Chat model、Embeddings、VectorStore、text splitter 都走 LangChain 介面，所以換 provider 或換向量資料庫只改一處；但流程本身是 `app/rag.py` 裡的三個普通函式，每一步送出什麼都看得到。

**LLM 與向量庫以 FastAPI dependency 注入。** 測試時用 `dependency_overrides` 換成假的 LLM 與記憶體內的 Qdrant，整條流程不需要 API key 或外部服務就能跑。

## 更換元件

- **LLM**：改 `.env` 的 `LLM_MODEL`（格式 `provider:model`）並提供該 provider 的 API key。Anthropic、OpenAI、OpenRouter、NVIDIA 的套件已安裝，設定範例見 `.env.example`。免費方案建議用 OpenRouter；NVIDIA API Catalog 的免費方案實測回應要等數分鐘、會 timeout，不建議使用。其他 provider 的接法見下一節。
- **Embedding 模型**：改 `EMBEDDING_MODEL` 後重新 ingest。預設的 `BAAI/bge-small-zh-v1.5` 小而快；`jinaai/jina-embeddings-v2-base-zh` 支援較長的輸入，但建索引的時間約為 7 倍。
- **向量資料庫**：替換 `app/vectorstore.py` 的 `get_store()` 與 `app/ingest.py` 的寫入呼叫。

## 整合新的 LLM provider

整個專案只有一個地方建立 LLM：`app/rag.py` 的 `get_llm()`，它把 `LLM_MODEL` 交給 LangChain 的 `init_chat_model`。所以多數 provider 不用改程式，只要裝套件、設環境變數。

### 一般情況：LangChain 已支援的 provider

以下以 Groq 為例，其他 provider 把名稱換掉即可。

1. **確認 provider 名稱與套件。** `init_chat_model` 支援的 provider 列在 [LangChain 文件](https://docs.langchain.com/oss/python/integrations/providers/overview)，每個對應一個 `langchain-<provider>` 套件。名稱打錯時，錯誤訊息也會列出所有支援的 provider。

2. **安裝套件。**

   ```bash
   uv add langchain-groq
   ```

   這會更新 `pyproject.toml` 與 `uv.lock`。新套件可能連帶調整其他相依套件的版本，裝完跑一次 `uv run pytest` 確認沒有壞掉。

3. **設定 `.env`。** API key 的環境變數名稱依套件而定，通常是 `<PROVIDER>_API_KEY`，以該套件的文件為準。

   ```bash
   LLM_MODEL=groq:<model id>
   GROQ_API_KEY=...
   ```

   `LLM_MODEL` 只以第一個冒號分隔 provider 與 model，所以 model id 本身含有 `/` 或 `:` 沒有問題，例如 `openrouter:vendor/model:free`。

   `compose.yaml` 會把整個 `.env` 傳進 container，不用為新的環境變數修改它。

4. **重建並驗證。**

   ```bash
   docker compose up -d --build
   docker compose exec api python -c "from app.rag import get_llm; print(get_llm().invoke('用繁體中文說你好').text)"
   ```

   第二行不經過檢索，直接確認 key、模型名稱與連線都正確，也能看出回應要等多久。

5. **在 `.env.example` 補上範例**，註明是否付費與實測的速度，之後才知道當初為什麼選或不選它。

### OpenAI 相容的端點

自架的推論服務（vLLM、LM Studio 等）或只提供 OpenAI 相容 API 的服務，不需要新套件，沿用 `openai` provider 並覆寫端點網址：

```bash
LLM_MODEL=openai:<model id>
OPENAI_API_BASE=https://your-endpoint/v1
OPENAI_API_KEY=...
```

### 需要額外參數時

`init_chat_model` 接受額外的關鍵字參數並轉交給對應的 chat model 類別。要固定 `temperature`、設定 `timeout`、或指定 `base_url` 時，改 `get_llm()` 這一處：

```python
@lru_cache
def get_llm() -> BaseChatModel:
    return init_chat_model(settings.llm_model, timeout=120)
```

各 provider 接受的參數不完全相同，加了之後要對每個會用到的 provider 測過。若參數需要依環境調整，在 `app/config.py` 的 `Settings` 加一個欄位再傳進來。

### LangChain 沒有支援的 provider

寫一個繼承 `BaseChatModel` 的類別（至少實作 `_generate`，要串流再實作 `_astream`），讓 `get_llm()` 回傳它。`app/vectorstore.py` 的 `FastEmbedEmbeddings` 是同樣做法用在 embedding 上的例子。其餘程式只依賴 `BaseChatModel` 介面，不需要跟著改。

### 換 provider 後要檢查的事

這個專案對 LLM 的要求只有三項，新的 provider 都要實際確認：

- **串流**：`/api/chat` 用 `astream()`。不支援串流的模型仍可運作，但回答會一次出現。
- **回應速度**：一題會發 2 到 3 個請求（改寫查詢、RAG 回答、無 RAG 回答）。單一請求要等上分鐘等級的服務會 timeout，NVIDIA 的免費方案就是這個情況。
- **是否遵守指示**：較小的模型可能不標 `[1]` 出處、輸出簡體中文、或在改寫查詢時多寫解釋。拿介面上的範例問題試幾題，比看規格表可靠。

測試（`uv run pytest`）使用假的 LLM，不會因為換 provider 而失敗，也因此無法替你驗證上述三項。

## 測試

```bash
uv run pytest
```

`tests/test_parsing.py` 以小段樣本文字驗證切分規則；`tests/test_api.py` 用假的 LLM 跑完整 API 流程。

## 已知限制與延伸方向

- **只有向量檢索。** 以條號直接查詢（「5.09(b)(7) 在講什麼」）效果不好。可以加上 Qdrant 的 sparse vector 做 hybrid search；中文需要先斷詞（例如 jieba），fastembed 內建的 BM25 不處理中文斷詞。
- **沒有 reranker。** 檢索結果直接依相似度排序。加一個 cross-encoder 重新排序前 20 筆，通常能改善前幾名的準確度。
- **圖片未處理。** 規則裡的球場圖與補述裡的示意圖沒有進索引。
- **條文之間的引用沒有展開。** 條文常寫「參照 6.01(a)」，目前不會自動把被引用的條文一起取回。
- **沒有評估集。** 要有系統地比較切分方式或 embedding 模型，需要先整理一份「問題 → 應命中條文」的清單，計算 recall@k。
- **單輪問答。** 沒有對話記憶，每個問題獨立處理。
- **答案的新舊取決於官方公布的 PDF。** 官網上的規則補述是 2024 年版，聯盟之後修改過的規定（例如投球計時）會依舊版條文作答。
