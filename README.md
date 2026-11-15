# 內部知識助理（Internal Knowledge Assistant）

公司內部的規章與 SOP 問答系統。員工用自然語言發問，系統**只從他有權限閱讀的文件**中找出相關條文，交給本機的大型語言模型整理成回答，並附上「哪份文件、第幾條」的出處；找不到依據時直接說找不到，不讓模型自行編造。

> 專案內的示範文件（`backend/data/sample_docs/`）全部是自行撰寫的**模擬資料**，不是任何公司的真實規章。

---

## 一、功能

| 使用者 | 可以做什麼 |
|---|---|
| 一般員工 | 註冊、登入；開新對話並提問；看回答的出處條文與原文；對回答按「有用／沒用」 |
| IT 管理員 | 上傳與作廢文件、重新處理失敗的文件；調整使用者角色與停用帳號；查看稽核紀錄；執行 RAG 評測並查看失敗題目 |
| 系統 | 15 分鐘短效登入憑證＋自動續期；閒置自動登出；所有重要動作寫入稽核紀錄 |

---

## 二、整體架構

```
瀏覽器（frontend/，原生 HTML／CSS／JavaScript）
   │  HTTP + JSON，Authorization: Bearer <access token>
   ▼
FastAPI 後端（backend/app/）
   ├─ 驗證：OAuth2 password flow、JWT、refresh token（HttpOnly cookie）
   ├─ 權限：路由層檢查角色、檢索層過濾文件等級
   ├─ 入庫：上傳 → 切塊 → 嵌入 → 寫入（背景執行）
   ├─ 問答：嵌入問題 → 混合檢索 → 拒答判斷 → 生成回答 → 存出處
   └─ 評測：固定題庫跑 Hit@k、MRR、拒答正確率、回應時間
   │                         │
   ▼                         ▼
PostgreSQL 16 + pgvector   Ollama（本機模型）
（Docker 容器）              ├─ bge-m3：文字 → 1024 維向量
                             └─ qwen2.5:3b：依參考資料生成回答
```

---

## 三、技術與職缺對應

| 職缺要求 | 這個專案怎麼用到 |
|---|---|
| LLM／RAG 應用開發 | 切塊、向量檢索＋BM25 關鍵字檢索、RRF 融合、拒答門檻、prompt 限制、出處標註 |
| 模型評測 | 26 題固定題庫，量 Hit@1、Hit@3、MRR、拒答正確率、p50／p95 回應時間 |
| Python／FastAPI | RESTful API、依賴注入、背景工作、統一錯誤格式、Pydantic 驗證 |
| PostgreSQL | 11 張表、外鍵刪除行為、CHECK／UNIQUE 約束、交易、pgvector 向量欄位、JSONB |
| OAuth 2.0／資安 | password 與 refresh_token 兩種 grant、Argon2 密碼雜湊、token 輪替與重複使用偵測、稽核紀錄 |
| 權限控管（RBAC） | 員工／主管／IT 管理員三種角色；文件分公開／部門／限閱三級 |
| Docker | PostgreSQL＋pgvector 以 Docker Compose 執行，資料存在 volume |
| 測試 | pytest 142 項：單元測試、資料庫整合測試、API 整合測試；以突變驗證確認測試有效 |

這個專案**沒有涵蓋**的職缺項目：Agent／Tool Use、Java Spring Boot、SQL Server、Shell 腳本、XML。

---

## 四、RAG 怎麼運作

### 1. 文件入庫（管理員上傳時）

```
上傳 .txt / .md
 → 檢查格式、大小、UTF-8
 → 算內容的 SHA-256，同部門已有相同內容就擋下（409）
 → 建立 pending 主檔，立刻回應 202
 → 【背景】依「第N條」切塊 → 每塊用 bge-m3 轉成向量
 → 【同一個交易】寫入所有 chunk、新版改 ready、同標題舊版改 deprecated
 → 任何一步失敗：整個 rollback，文件標成 failed（可重新處理）
```

只有 `ready` 的文件會被檢索，所以處理到一半或失敗的文件不會出現在回答裡；新舊版本也不會同時被查到。

### 2. 提問

```
問題
 → bge-m3 轉成向量
 → 混合檢索（兩路都已套用權限條件）
     ├─ 向量檢索：pgvector 餘弦相似度，找語意相近的條文
     └─ BM25 關鍵字檢索：中文以兩字一組切詞，找字面相符的條文
 → RRF 依名次融合兩路結果，取前 5 筆
 → 拒答判斷：最相近那筆的向量相似度 < 0.62 → 直接回覆「找不到依據」，不呼叫模型
 → 把條文（標註文件名與條號）放進 prompt，qwen2.5:3b 生成回答
 → 存下提問、回答、出處快照，回傳給前端
```

| 設計 | 原因 |
|---|---|
| 為什麼不用微調讓模型記住文件 | 文件會改版、作廢，還要依使用者權限隱藏；RAG 改資料庫就生效，也能附出處 |
| 為什麼要混合檢索 | 向量懂語意但抓不準條號與專有名詞，關鍵字檢索正好相反 |
| 為什麼用 RRF | 兩種分數的尺度不同，RRF 只看名次，不需要調權重 |
| 拒答為什麼看向量相似度，不看 RRF 分數 | RRF 只反映名次，再不相關的問題也有第一名；相似度才有絕對意義 |
| 兩道防線避免亂答 | 第一道是相似度門檻，不夠像就不呼叫模型；第二道是 prompt 規定只能依參考資料回答，沒有相關規定就回答「找不到依據」 |
| 模型服務掛掉 | 連線失敗、逾時、5xx 會重試（間隔 1、2、4 秒），最後回覆友善訊息 |

---

## 五、權限設計

**兩層權限**

1. **路由層（誰能呼叫這個 API）**：文件管理、使用者管理、稽核、評測只限 IT 管理員；不符回 403。
2. **資料層（誰看得到哪份文件）**：權限條件直接寫在檢索的 SQL 裡，沒權限的條文根本不會被撈出來，模型也就看不到。

| 文件等級 | 誰看得到 |
|---|---|
| public 公開 | 所有人 |
| dept 部門 | 同部門的人 |
| restricted 限閱 | IT 管理員 |

其他規則：

- 對話只有本人能看。別人的對話回 404 而不是 403，不透露它存在。
- 自助註冊一律是一般員工，不能自選角色；角色只能由 IT 管理員調整。
- 管理員不能停用或降級自己；停用帳號時，該帳號的 refresh token 一併作廢。
- 出處的原文每次讀取時都依「目前」的權限重新檢查，文件改成限閱後，舊回答的原文也看不到了。

---

## 六、登入與資安

| 項目 | 做法 |
|---|---|
| 密碼 | Argon2id 雜湊，不存明文；帳號不存在和密碼錯誤回同一句話 |
| access token | JWT，15 分鐘到期，放在 Authorization 標頭 |
| refresh token | 32 位元組亂數，放在 HttpOnly cookie（JavaScript 讀不到）；資料庫只存 SHA-256 雜湊 |
| 輪替 | 每次續期都換新 token、作廢舊的；作廢超過 10 秒的舊 token 又被使用，視為被盜，作廢該使用者全部 token |
| 閒置登出 | 前端 15 分鐘無操作就登出；伺服器端超過 30 分鐘沒有活動也拒絕續期 |
| 稽核 | 記錄誰、何時、哪個 IP、做了什麼（登入成功或失敗、提問、上傳、改權限、評測）；不記提問內容與文件本文 |
| CORS | 只允許列出的前端網址帶 cookie 呼叫 API |

---

## 七、評測結果

題庫：`backend/data/eval_cases.json`，共 26 題。

| 題型 | 題數 | 內容 |
|---|---|---|
| answer 應回答 | 18 | 每題有標準答案（文件與條號），涵蓋 7 份文件、5 個部門的提問身分 |
| permission 應拒答（越權） | 4 | 問的是自己部門看不到的文件 |
| refuse 應拒答（題庫外） | 4 | 文件裡沒有的問題 |

結果（bge-m3＋qwen2.5:3b，本機 CPU，每一列是一次完整評測）：

| 批次 | 設定 | Hit@1／Hit@3／MRR | 拒答正確率 | 應回答卻被模型說找不到依據 | 回應時間 p50／p95 |
|---|---|---|---|---|---|
| 1 | 門檻 0.57、第一版 prompt | 100%／100%／1.00 | 92.3%（2 題該拒答卻放行，但模型都回答「找不到依據」） | 1 題 | 5.4／8.4 秒 |
| 2 | 門檻 0.62、第一版 prompt | 100%／100%／1.00 | 100% | 2 題 | 2.5／11.6 秒 |
| 3 | 門檻 0.62、第二版 prompt | 100%／100%／1.00 | 100% | 1 題 | 8.3／13.6 秒 |
| 4 | 同上，重跑一次 | 100%／100%／1.00 | 100% | 1 題 | 2.6／4.2 秒 |

調整過程：

1. **門檻**：量出應回答題目中，最相近條文的相似度最低是 0.645；應拒答題目最高是 0.608。取缺口中間值 0.62 後，拒答正確率由 92.3% 變成 100%。
2. **prompt**：第一版只寫「資料中沒有就回答找不到依據」，小模型遇到用詞不同（例如「特休」對「特別休假」）或「可不可以」這類問題時會過度拒答。第二版補上「用詞不同但意思相同也算有依據」與「是非題依條文的允許或禁止回答」。之後「特休」那題穩定答對；剩下的 1 題（程式碼可不可以寫密碼）答案內容正確，但開頭先寫了「找不到依據」。
3. **第二道防線有效**：批次 1 漏拒的 2 題，模型都依 prompt 回答「找不到依據」，沒有亂編。

如實說明的限制：

- 門檻與 prompt 都是用**同一份題庫**調整的，數字偏樂觀；要更可信，需要另一份沒拿來調整的測試題。
- 文件是 7 份短的模擬規章，比真實環境單純，檢索指標容易拿到滿分。
- qwen2.5:3b 偶爾會**混入簡體字**，或**先說「找不到依據」再給出正確答案**。可改用較大的模型，或對輸出做後處理（例如繁簡轉換）。
- 回應時間受模型是否已載入與機器負載影響很大；第一次呼叫（冷啟動）可能超過 40 秒。

---

## 八、資料表（11 張）

| 資料表 | 內容 | 重點 |
|---|---|---|
| `departments` | 部門 | 還有使用者或文件時不能刪除（RESTRICT） |
| `users` | 使用者 | Argon2 雜湊、角色 CHECK 約束 |
| `documents` | 文件主檔 | 等級、狀態、版本、checksum |
| `document_chunks` | 切塊與向量 | `vector(1024)`；文件刪除時一起刪除 |
| `conversations` | 對話 | UUID 主鍵；使用者刪除時一起刪除 |
| `messages` | 提問與回答 | 是否拒答、回應時間、回饋 |
| `message_citations` | 回答的出處 | 另存文件標題、版本、條號的快照；chunk 刪除時只設為 NULL |
| `audit_logs` | 稽核紀錄 | INET 型別存 IP；使用者刪除時保留紀錄 |
| `refresh_tokens` | refresh token | 只存雜湊；有撤銷時間就代表已作廢 |
| `eval_runs` | 評測批次 | 當時的模型與參數、指標（JSONB） |
| `eval_results` | 評測每題結果 | 標準答案名次、是否拒答、模型回答 |

---

## 九、API 一覽（前綴 `/api/v1`）

| 方法與路徑 | 用途 | 權限 |
|---|---|---|
| `POST /auth/token` | 登入（`grant_type=password`）或續期（`grant_type=refresh_token`） | 公開 |
| `POST /auth/revoke` | 登出 | 公開 |
| `POST /users` | 自助註冊 | 公開 |
| `GET /departments` | 部門清單 | 公開 |
| `GET /me` | 我的資料 | 登入 |
| `GET`／`POST /conversations`、`DELETE /conversations/{id}` | 對話列表、新增、刪除 | 登入（只限本人） |
| `GET`／`POST /conversations/{id}/messages` | 讀取訊息、提問 | 登入（只限本人） |
| `PUT /messages/{id}/feedback` | 回饋有用或沒用 | 登入（只限本人） |
| `GET`／`POST /documents`、`PATCH /documents/{id}` | 文件列表、上傳（202）、修改或作廢 | IT 管理員 |
| `POST /documents/{id}/processing-jobs` | 重新處理失敗的文件（202） | IT 管理員 |
| `GET /users`、`PATCH /users/{id}` | 使用者列表、改角色或停用 | IT 管理員 |
| `GET /audit-logs` | 稽核紀錄 | IT 管理員 |
| `GET`／`POST /eval-runs`、`GET /eval-runs/{id}/results` | 評測批次、執行評測（202）、每題結果 | IT 管理員 |

錯誤一律回 `{"code": ..., "message": ...}`。啟動後可在 `http://127.0.0.1:7999/docs` 看互動式 API 文件。

---

## 十、專案結構

```
backend/
  app/
    core/        設定、資料庫連線、密碼與 JWT、驗證依賴、錯誤格式
                 RAG 元件：chunker 切塊、bm25 關鍵字檢索、rrf 融合、retriever 檢索與權限、llm_service 呼叫模型
    models/      資料表定義（SQLAlchemy）
    schemas/     請求與回應格式（Pydantic）
    services/    商業邏輯：rag 問答、ingestion 入庫、chat 對話、auth_service 註冊登入、
                 token_service refresh token、audit 稽核、evaluation 評測
    routers/     API 端點
    main.py      建立應用程式、CORS、錯誤處理、掛上路由、啟動時清理中斷的背景工作
  scripts/       建表、建部門、建立管理員、匯入示範文件、命令列評測
  data/          示範文件（模擬資料）與評測題庫
  tests/         pytest 測試
frontend/        網頁介面
docker-compose.yml  PostgreSQL + pgvector
```

---

## 十一、啟動方式（Windows）

**事前準備**：Docker Desktop、Python 3.12 以上、[Ollama](https://ollama.com/)。

1. 下載模型：
   ```bash
   ollama pull bge-m3
   ```
   ```bash
   ollama pull qwen2.5:3b
   ```
2. 在 `backend/.env` 設定（不進版控）：`APP_NAME`、`APP_ENV`、`DEBUG`、`SECRET_KEY`（至少 32 字元的亂數）、`POSTGRES_DATABASE`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_PORT`。其餘設定都有預設值，見 `backend/app/core/config.py`。
3. 啟動資料庫（在專案根目錄）：
   ```bash
   docker compose --env-file backend/.env up -d
   ```
4. 安裝套件並初始化（在 `backend` 目錄）：
   ```bash
   python -m venv .venv
   ```
   ```bash
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
   ```bash
   .venv\Scripts\python.exe -m scripts.create_tables
   ```
   ```bash
   .venv\Scripts\python.exe -m scripts.seed_departments
   ```
   ```bash
   .venv\Scripts\python.exe -m scripts.create_admin admin@company.com ops
   ```
   ```bash
   .venv\Scripts\python.exe -m scripts.import_samples
   ```
5. 啟動後端（在 `backend` 目錄）：
   ```bash
   .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 7999
   ```
6. 啟動前端（在專案根目錄），然後用瀏覽器開 `http://127.0.0.1:5500/frontend/`。網址要用 `127.0.0.1`，不要用 `localhost`，否則重新整理後會被登出（cookie 的跨站限制）：
   ```bash
   python -m http.server 5500
   ```
7. 命令列評測（選用）：
   ```bash
   .venv\Scripts\python.exe -m scripts.run_eval
   ```

---

## 十二、測試

```bash
.venv\Scripts\python.exe -m pytest -q
```

- 共 142 項。資料庫測試會自動建立臨時資料庫 `ika_pytest_tmp`，測完刪除，不會動到正式資料。
- 模型用假的，不需要 Ollama；另有 2 項會呼叫真的 Ollama，沒開時自動略過。
- 曾以「突變驗證」檢查測試有效：故意拿掉權限檢查、交易、token 輪替等 30 多處關鍵邏輯，測試都會失敗。

---

## 十三、已知限制與下一步

| 限制 | 下一步 |
|---|---|
| 只支援 .txt／.md | 加入 PDF、Word 解析（pypdf、python-docx） |
| 背景工作用 FastAPI BackgroundTasks，重啟會中斷（目前啟動時會把中斷的工作標成失敗） | 改用 Celery 等任務佇列 |
| 建表用 `create_all`，無法修改既有的表 | 改用 Alembic 管理資料庫遷移 |
| 向量欄位沒有索引，資料多了會變慢 | 加 HNSW 索引，並處理「先過濾權限、筆數不足」的問題 |
| 評測題庫小、且與調整用的題目相同 | 擴充題庫，並分出不參與調整的測試集 |
| 小模型偶爾混入簡體字或自相矛盾 | 換較大的模型，或做輸出後處理 |
| 沒有 HTTPS、沒有登入失敗鎖定 | 上線前加反向代理與 HTTPS、登入失敗次數限制 |
