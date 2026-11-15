# 內部知識助理前端（HTML / CSS / Vanilla JavaScript）

此版本依專案企劃書第 8 節與現有 FastAPI API 合約製作，使用原生 HTML、CSS、JavaScript，不使用 React / Vite。**不會修改原 GitHub repo**，可先在本機獨立預覽。

## 1. 啟動展示模式

在此資料夾開啟 PowerShell：

```powershell
python -m http.server 5500
```

瀏覽器開啟：

- `http://localhost:5500/?demo`

展示模式使用明確標示的假資料，可預覽登入、對話、引用卡、IT 管理中心、文件、使用者、稽核及評測頁面。展示模式不會建立真實帳號、上傳文件或呼叫後端。

登入欄位已預填展示帳號。若要看 IT 管理頁，使用 `it.admin@company.test`；一般員工可輸入其他 email。

## 2. 串接 FastAPI

預設 API 位址：

```text
http://127.0.0.1:7999/api/v1
```

後端啟動後，以不帶 `?demo` 的網址開啟：

```text
http://localhost:5500
```

因為前端與後端不同 origin，請在專案根目錄 `.env` 設定 CORS：

```env
CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
```

若設定類別的環境變數名稱使用 Pydantic Settings 預設規則，`cors_origins` 對應 `CORS_ORIGINS`。修改後重新啟動 FastAPI。

## 3. 已接上的 API

| 功能 | API |
|---|---|
| 登入／更新權杖 | `POST /auth/token` |
| 登出撤銷 | `POST /auth/revoke` |
| 註冊 | `POST /users` |
| 部門下拉 | `GET /departments` |
| 目前使用者 | `GET /me` |
| 對話列表／建立／刪除 | `GET/POST/DELETE /conversations` |
| 對話訊息／提問 | `GET/POST /conversations/{id}/messages` |
| 回答回饋 | `PUT /messages/{id}/feedback` |
| 文件列表／上傳／修改／重新處理 | `/documents` |
| 使用者列表／修改 | `/users` |
| 稽核 | `GET /audit-logs` |
| 評測批次／結果 | `/eval-runs` |

Access JWT 只保存在 JavaScript 記憶體；refresh token 由後端以 HttpOnly Cookie 管理。前端 15 分鐘無鍵盤、滑鼠、觸控或捲動操作會呼叫撤銷端點並登出。

## 4. 目前發現的後端合約缺口

企劃書要求「點擊出處卡可展開原文」，但目前 `CitationOut` 只有 `rank / doc_title / version / article_no / score`，沒有原文內容，也沒有對應的 chunk 明細 API。因此正式 API 模式會明確提示目前尚未提供原文，而不會假造後端資料。要完成該功能，需在後端新增授權後的引用段落內容欄位或 chunk 明細端點。

另外，企劃書的閒置登出流程要求撤銷 refresh token；前端已做 15 分鐘計時，但瀏覽器關閉或裝置突然斷線時仍須由後端 refresh token TTL／伺服器端閒置檢查兜底。

## 5. 注意

- 前端隱藏 IT 導覽只改善使用體驗，不構成安全控制；所有權限仍由 FastAPI 驗證。
- 目前文件上傳 UI 提供 PDF、DOCX、TXT 選擇；後端實際支援格式仍以服務層驗證為準。
- 正式環境必須使用 HTTPS，並將 refresh cookie 的 `Secure` 設為 `True`。
- 字型目前使用 Google Fonts；若部署環境完全內網，需改成本機字型或移除遠端字型載入。
