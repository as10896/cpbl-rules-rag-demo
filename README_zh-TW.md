# CPBL 規則 RAG

[![English](https://img.shields.io/badge/English-read-brightgreen)](README.md)
[![繁體中文](https://img.shields.io/badge/%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-read-blue)](README_zh-TW.md)

這是一個小型 demo，示範如何使用 LangChain 和 Qdrant 建立
RAG（Retrieval-Augmented Generation，檢索增強生成）應用。後端以 FastAPI
提供服務，整個專案透過 Docker Compose 執行。

這個專案主要示範：

- 按照文件原本的結構切分內容，並在每個 chunk 開頭保留引用資訊
- 在檢索前先改寫使用者的問題
- 以串流方式輸出回答，並讓引用連回來源頁面
- 將同一個問題的「有 RAG」與「沒有 RAG」回答並排比較
- 只透過設定就能切換 LLM provider
- 用實際核對過的案例，看看 RAG 能解決什麼，以及它仍然會在哪些地方出錯

這裡使用的知識庫只是範例，內容來自中華職棒（CPBL）的官方規則文件。你可以輸入比賽情境或規則問題，系統會找出相關條文，並在回答中附上條號、頁碼和官方
PDF 連結。

RAG 的做法本身和棒球沒有關係。和這份語料庫綁定的部分只有 `app/corpus.py`
的文件設定、`app/rag.py` 的 prompts，以及 UI 裡的範例問題。

由於語料庫是繁體中文，prompt 和 Web UI
也都是繁體中文，問題請使用中文輸入。

## 執行畫面

每個問題會回答兩次：左邊是有使用檢索的結果，右邊是不使用檢索的結果；下方則會列出實際檢索到的條文。

![詢問總教練一場比賽可以挑戰幾次](docs/screenshots/replay-challenge.png)

## RAG 能解決什麼？又不能解決什麼？

RAG 並非萬能。這邊以三個案例說明，三題的兩邊都使用同一個免費模型，回答也都逐句和原始 PDF 核對過：

- [挑戰次數](docs/screenshots/replay-challenge.png)：總教練一場比賽可以挑戰幾次？挑戰失敗會怎樣？
- [投球計時](docs/screenshots/pitch-timer.png)：投手投球計時是幾秒？超過時間怎麼判？
- [本壘衝撞](docs/screenshots/home-plate-collision.png)：捕手沒有持球卻擋住本壘板，跑者撞上去，怎麼判？

挑戰次數和投球計時可以看到 RAG 有幫助的地方，投球計時和本壘衝撞則可以看到它仍然會犯的錯。

### 能改善的問題：模型自己編造規定

沒有文件可以參考時，模型可能會用非常肯定的語氣，講出實際上不存在的規定：

- 挑戰次數：模型編造了「第二次挑戰失敗會罰款新台幣一萬元」。三份文件都沒有這項罰則。
- 投球計時：模型說一壘或三壘有跑者，或兩人出局時，不適用投球計時。但補述明確寫的是壘上有人時為
  25 秒，而且沒有出局數的例外。

加入文件後，這兩題的回答都和引用的條文一致。像是問「挑戰失敗之後會怎樣」時，RAG
會回答規章沒有說明，而不是自行猜測。

### RAG 仍然解決不了的問題

- **文件過時，回答也會跟著過時。** 投球計時的回答是 20 秒和 25 秒，和
  2024 年版補述完全一致，而這也是聯盟目前公布的最新版本。2026
  年初的新聞報導指出，這兩個時間限制後來已經縮短。如果這項變更屬實，這個回答雖然忠於來源，內容卻仍然過時。
- **沒有被檢索到的內容，就不會進入回答。**
  在本壘衝撞的案例中，補述
  3.26 被切成兩個
  chunk，但只檢索到後半段。前半段提到跑壘員若惡意衝撞，應判出局並驅逐出場；這段內容沒有送進模型，所以回答自然沒有提到。
- **檢索到正確內容，也可能被模型誤讀。**
  同一個回答指出跑者撞上捕手時，應依規則 6.01(i)(1)
  判出局。但該規則的註解寫明，如果捕手正在阻擋跑壘員的跑壘路徑，就不應認定跑壘員違規，而這正是題目描述的情境。這段註解其實就在第一個被檢索到的
  chunk 裡。
- **同一個問題不一定每次都得到相同結果。** Query rewrite
  每次可能不同，而檢索結果又會受到改寫內容影響。因此同一個問題可能一次回答得很完整，下一次卻只找到部分相關內容（見「已知限制與延伸方向」）。

值得注意的是，本壘衝撞這題在沒有 RAG
的情況下，其實也得到「跑者安全」這個基本判決，只是說明比較簡略。RAG
在這一題沒有改變最後的判決；它主要增加了可追溯的引用，而也正因為有引用，才比較容易發現上面提到的問題。

## 快速開始

1.  建立 `.env`，並填入
    `OPENROUTER_API_KEY`。預設使用免費模型，每天有請求數量限制（見下方說明）；其他
    provider 的設定可以參考 `.env.example`。

    ```bash
    cp .env.example .env
    ```

2.  建置 Docker image。

    ```bash
    docker compose build
    ```

3.  下載 PDF 並建立索引。整個過程大約需要 2 分鐘，Qdrant 會自動啟動。

    ```bash
    docker compose run --rm api python -m app.ingest
    ```

4.  啟動服務。

    ```bash
    docker compose up -d
    ```

> **免費模型額度**
>
> 截至 2026 年 9 月，OpenRouter 的免費模型每個帳號每天最多 50
> 個請求；帳號累計購買 10 credits 後，上限會變成 1000 個。每分鐘則限制
> 20 個請求。這些數字可能會調整，請以 [OpenRouter
> 的限制說明](https://openrouter.ai/docs/api-reference/limits) 為準。
>
> 一個問題最多會送出 3 個請求：query rewrite、RAG answer，以及 no-RAG
> answer。因此每天 50 個請求大約可以問 16 題。取消「同時顯示不使用 RAG
> 的回答」或「檢索前先改寫查詢」，各可以少送出一個請求。
>
> 額度用完後，UI 會顯示
> `Rate limit exceeded: free-models-per-day`，直到隔天額度恢復。

索引會在 API 啟動前建立完成，因此服務啟動後就可以直接使用。索引會保存在
volume 中，只有文件內容、chunking 設定或 embedding model
改變時，才需要重新執行 ingest。

- Web UI：http://localhost:8000
- API docs：http://localhost:8000/docs
- Qdrant dashboard：http://localhost:6333/dashboard

開發時可以使用 `docker compose up --watch`。修改 `app/` 或 `frontend/`
底下的檔案後，變更會自動同步到 container。

## 語料庫

三份文件都來自[中華職棒官方網站](https://www.cpbl.com.tw/)，由 `ingest`
自動下載到 `data/`：

| 文件 | 內容 | 切分單位 |
|---|---|---|
| 棒球規則（2026） | 比賽規則與相關用語定義 | 條號（`5.07`）、定義詞條（`INFIELD FLY`） |
| 裁判執法手冊規則補述 | 中職對特定情境的執法解釋 | 條號（`3.26`） |
| 聯盟規章（2026） | 競賽規程、球員註冊、懲處等 | 條文（`第45條`） |

這些文件的著作權屬於中華職業棒球大聯盟，而且文件本身標示禁止複製轉載，因此
`data/` 不會放進版本控制。

官方發布新版文件後，可以執行：

```bash
python -m app.ingest --refresh
```

如果下載失敗，通常代表官網更換了 PDF 的網址；這時到 `app/corpus.py`
更新對應的 URL。

## 運作流程

```text
建立索引（app/ingest.py）
  PDF ─→ 逐頁抽取文字，移除頁碼與頁眉
      ─→ 依條號整理成條文
      ─→ 過長的條文再切成多個 chunk
      ─→ 在每個 chunk 開頭加入引用資訊
      ─→ embedding ─→ Qdrant

問答（POST /api/chat，SSE 串流）
  問題 ─→ LLM 改寫成規則文件使用的用語
       ─→ 原問題與改寫後的問題各檢索一次，合併兩份排名
       ─→ 取前 k 個結果，每條條文最多保留 3 個 chunk
       ─→ 為 chunk 編號並放入 prompt
       ─→ LLM 串流輸出回答，以 [1][2] 等標記引用來源
```

完整流程也可以參考循序圖：[docs/rag-sequence.mmd](docs/rag-sequence.mmd)。

## 程式碼導覽

| 檔案 | 職責 |
|---|---|
| `app/corpus.py` | 三份文件的 URL 與版面規則（頁碼、頁眉、條號的 regex），以及文件下載 |
| `app/parsing.py` | 文字清理與切分，全部使用純函式 |
| `app/vectorstore.py` | fastembed 的 LangChain adapter，以及 Qdrant 連線 |
| `app/ingest.py` | 建立索引的指令 |
| `app/rag.py` | prompt、query rewrite、retrieval 與結果合併 |
| `app/main.py` | FastAPI endpoints |
| `frontend/index.html` | 單頁 UI，不需要 build step |

## API

| Endpoint | 說明 |
|---|---|
| `GET /api/search?q=&k=` | 只執行檢索，回傳 chunk 與 similarity score。調整 chunking 或 embedding model 時，可以用它觀察檢索結果 |
| `POST /api/chat` | 接收 `{question, use_rag, rewrite, top_k}`，並以 SSE 串流回傳 `rewrite`、`sources`、`token`、`model`、`error` 等事件。`rewrite` 和 `model` 會帶上實際回應的模型名稱 |

```bash
curl --get localhost:8000/api/search --data-urlencode "q=延長賽最多打幾局" | jq '.[] | {section, title, score}'
```

## 設計決策

### 1. 依條號切分，而不是固定長度

規則文件的主要語意單位是「條」，而引用時也需要保留條號。因此只有單一條文超過
`CHUNK_SIZE` 時，才會再使用 `RecursiveCharacterTextSplitter` 切分。

### 2. 每個 chunk 開頭都保留引用資訊

例如：

```text
《棒球規則》5.09 出局｜5.09(b) 跑壘員出局
```

長條文被切成多個 chunk 後，後面的 chunk
本身可能看不出來屬於哪一條。補述第六章的「可更改／不可更改判決」就是一個明顯的例子：如果沒有這個
header，兩份清單裡的項目就很難區分。

### 3. 在檢索前先改寫 query

球迷可能會說「洋將」、「挑戰」、「擋壘」，但規則文件使用的是「外國籍球員」、「即時重播輔助判決」、「妨礙跑壘」。

可以在 UI 中取消勾選「檢索前先改寫查詢」，然後輸入：

> 洋將一場比賽最多可以同時上幾個？

比較兩種設定下的檢索結果，就能看到 query rewrite 的差異。

### 4. 合併兩次檢索的排名，並限制單一條文能佔多少結果

原始問題與改寫後的 query 會分開檢索，再透過 reciprocal rank fusion
合併排名。

不同 query 的 similarity score
不能直接互相比較。如果單純把兩次檢索的結果依分數排序，一個改寫失準的
query 可能反而把原始問題找到的好結果擠掉。

合併後，每條條文最多保留 3 個 chunk。原因是長條文切成很多相似 chunk
後，很容易一次佔滿所有結果，把其他文件裡較短但同樣相關的內容擠出去。

這兩個設定都是根據範例問題實測後做出的取捨，不是保證一定有效。例如：

- 上限設成 2 個 chunk 時，會漏掉包含投球計時秒數的 chunk。
- 即使兩項設定都啟用，本壘衝撞的補述在針對該問題收集的 8 個 query
  rewrite 中，也只有 5 次成功被檢索到。

### 5. 使用 LangChain 作為整合層

LangChain 是目前常見的 LLM application framework，因此這裡的寫法和許多
RAG 專案相近，也比較容易把這套做法延伸到其他專案。

它的統一介面也讓 LLM provider 可以透過設定切換：`init_chat_model` 會根據
`LLM_MODEL` 建立對應的 client，因此 Anthropic、OpenAI 和 OpenRouter
之間切換時，只需要修改 `.env`。

Text splitter 和 Qdrant integration 也都有現成的元件。

代價是程式和實際 API 呼叫之間多了一層
abstraction，這也是下一個設計決定的原因。

### 6. 使用 LangChain 的元件，但不使用它的 chains 或 agents

Chat model、embeddings、vector store 和 text splitter 都透過 LangChain
的介面，因此未來要換 provider 或 vector database 時，只需要改一個地方。

但實際的 RAG 流程沒有交給 chain 或 agent，而是直接寫在 `app/rag.py`
的三個普通函式裡。這樣每一步實際送出了什麼內容都很清楚，也比較方便除錯。

### 7. 向量資料庫選用 Qdrant

Qdrant 只需要一個 container，很適合這個 Compose
架構；它也提供管理介面，可以直接查看儲存的 chunk 和 metadata，對理解
retrieval 的行為很方便。

Qdrant client 也支援 in-memory mode，因此 API
測試可以直接使用它，不需要啟動實際的 Qdrant server。

此外，Qdrant 原生支援 sparse vectors，之後如果要加入 hybrid
search，不需要更換資料庫。

另一個考慮過的方案是 pgvector。如果應用本身就需要 PostgreSQL
儲存關聯式資料，pgvector 會更適合；但這個 demo 除了 chunk
之外沒有其他資料需要儲存，所以選擇 Qdrant。

### 8. 透過 FastAPI dependency injection 注入 LLM 和 vector store

測試時可以用 `dependency_overrides` 替換成 fake LLM 和 in-memory
Qdrant，讓整個流程不需要 API key 或任何外部服務就能執行。

## 更換元件

- **LLM**：修改 `.env` 的 `LLM_MODEL`（格式為
  `provider:model`），並設定該 provider 的 API key。Anthropic、OpenAI
  和 OpenRouter 的套件都已安裝，設定範例可以參考
  `.env.example`。如果要使用免費模型，建議在 OpenRouter
  上指定一個固定的免費模型，不要使用 `openrouter/free`
  router，因為它每次 request 都會隨機選模型，也可能選到不支援 chat
  的模型。其他 provider 的加入方式見下一節。
- **Embedding model**：修改 `EMBEDDING_MODEL`，然後重新執行
  ingest。預設的 `BAAI/bge-small-zh-v1.5`
  體積小、速度快；`jinaai/jina-embeddings-v2-base-zh`
  可以處理更長的輸入，但建立索引的時間約是前者的 7 倍。
- **Vector database**：修改 `app/vectorstore.py` 的
  `get_store()`，以及 `app/ingest.py` 中寫入資料的部分。

## 加入新的 LLM provider

整個專案只有一個地方負責建立 LLM：`app/rag.py` 的 `get_llm()`。它會把
`LLM_MODEL` 傳給 LangChain 的 `init_chat_model`。

因此，大部分 provider
都不需要修改既有程式，只需要安裝對應套件並設定環境變數。

### 一般情況：LangChain 已支援的 provider

以下以 Groq 為例，換成其他 provider 時流程基本相同。

1.  **確認 provider 名稱與套件。**

    `init_chat_model` 支援的 provider 可以參考 [LangChain
    文件](https://docs.langchain.com/oss/python/integrations/providers/overview)。每個
    provider 都有對應的 `langchain-<provider>` 套件。

    如果 provider 名稱打錯，錯誤訊息也會列出目前支援的 provider。

2.  **安裝套件。**

    ```bash
    uv add langchain-groq
    ```

    這會更新 `pyproject.toml` 和 `uv.lock`。新增套件可能連帶調整其他
    dependencies 的版本，因此安裝後建議執行一次 `uv run pytest`。

3.  **設定 `.env`。**

    API key 的環境變數名稱依套件而定，通常是
    `<PROVIDER>_API_KEY`，實際名稱請以該套件的文件為準。

    ```bash
    LLM_MODEL=groq:<model id>
    GROQ_API_KEY=...
    ```

    `LLM_MODEL` 只會用第一個冒號分隔 provider 和 model，所以 model ID
    本身包含 `/` 或 `:` 也沒問題，例如：

    ```text
    openrouter:vendor/model:free
    ```

    `compose.yaml` 會把整個 `.env` 傳進
    container，因此新增環境變數時不需要修改 Compose 設定。

4.  **重新建置並測試。**

    ```bash
    docker compose up -d --build
    docker compose exec api python -c "from app.rag import get_llm; print(get_llm().invoke('用繁體中文說你好').text)"
    ```

    第二個指令不會經過 retrieval，而是直接測試 API key、model name
    和連線是否正常，也可以順便觀察 response time。

5.  **在 `.env.example` 補上設定範例。**

    建議註明這個 provider 是否需要付費，以及實測的 response
    time，讓之後的人知道當初為什麼選用或沒有選用它。

### OpenAI-compatible endpoints

如果是自架的 inference server（例如 vLLM、LM Studio），或其他只提供
OpenAI-compatible API 的服務，不需要額外安裝 provider package。

直接使用 `openai` provider，並覆寫 endpoint：

```bash
LLM_MODEL=openai:<model id>
OPENAI_API_BASE=https://your-endpoint/v1
OPENAI_API_KEY=...
```

### 需要額外參數時

`init_chat_model` 接受額外的 keyword arguments，並會傳給底層的 chat
model class。

例如要固定 `temperature`、設定 `timeout` 或指定 `base_url`，可以直接修改
`get_llm()`：

```python
@lru_cache
def get_llm() -> BaseChatModel:
    return init_chat_model(settings.llm_model, timeout=120)
```

不同 provider 支援的參數不一定相同，因此新增參數後，使用到的每個
provider 都應該實際測試一次。

如果某個參數需要依環境切換，可以在 `app/config.py` 的 `Settings`
新增欄位，再傳進 `get_llm()`。

### LangChain 沒有支援的 provider

可以自行建立一個繼承 `BaseChatModel` 的 class，至少實作
`_generate`；如果需要 streaming，再實作 `_astream`，最後讓 `get_llm()`
回傳這個 class。

`app/vectorstore.py` 裡的 `FastEmbedEmbeddings`
也是類似的做法，只是應用在 embedding 上。

其他程式只依賴 `BaseChatModel` 介面，因此不需要跟著修改。

### 更換 provider 後要確認什麼？

換成新的 provider 後，至少確認以下幾件事：

- **Streaming**：`/api/chat` 使用 `astream()`。即使模型不支援
  streaming，仍然可以運作，只是整個回答會一次出現。
- **Response time**：一題會送出 2～3 個 request（query rewrite、RAG
  answer、no-RAG answer）。如果單次 request 就需要幾分鐘，API 可能會
  timeout。
- **是否遵守 prompt 指示**：較小的模型可能漏掉 `[1]`
  引用、輸出簡體中文，或在 query rewrite 時額外加入說明。實際拿 UI
  裡的範例問題跑幾次，通常比只看模型規格更有參考價值。
- **實際使用的模型**：UI 會在每個回答下方，以及改寫後的 query 旁邊顯示
  provider 回報的 model name。如果使用 router，每次 request
  可能選到不同模型，這也會造成回答品質出現明顯差異。

測試（`uv run pytest`）使用 fake LLM，因此不會因為更換 provider
而失敗；同樣地，它也無法替你驗證上面這些 provider-specific 的行為。

## 測試

```bash
uv run pytest
```

`tests/test_parsing.py`
會用短篇樣本文字測試切分規則；`tests/test_api.py` 則使用 fake LLM
跑完整的 API flow。

## 已知限制與延伸方向

- **目前只有 vector search。** 直接用條號查詢，例如「5.09(b)(7)
  在講什麼」，效果較差。可以利用 Qdrant 的 sparse vectors 加入 hybrid
  search。中文則需要先做斷詞（例如 jieba），因為 fastembed 內建的 BM25
  不會處理中文斷詞。
- **Retrieval 受到 query rewrite 影響。** Rewrite 是由 LLM
  產生，而且每次執行可能不同。如果改寫後沒有使用相關條文中的關鍵用語，那份條文就可能檢索不到，最後產生一個看起來很有把握、但其實不完整的回答。因此同一個問題可能這次回答完整，下次只回答一部分。
- **目前沒有 reranker。** 結果只依 similarity 排序。可以把前 20
  筆結果交給 cross-encoder
  重新排序，通常有助於提升前幾筆結果的準確度。
- **目前沒有處理圖片。**
  規則中的球場示意圖，以及補述中的插圖，都沒有被加入索引。
- **目前不會追蹤條文之間的交叉引用。** 例如條文寫著「參照
  6.01(a)」時，系統不會自動把被引用的條文一起取回。
- **目前沒有 evaluation set。** 如果要系統性比較不同 chunking strategy
  或 embedding model，需要先建立一組「問題 →
  應該檢索到哪些條文」的資料，才能計算 recall@k。
- **目前是單輪問答。** 沒有 conversation
  memory，每個問題都會獨立處理。
- **回答內容的新舊取決於官方 PDF。** 官網目前的規則補述是 2024
  年版，因此如果聯盟之後修改規定，例如投球計時，系統仍會按照舊版文件回答。
