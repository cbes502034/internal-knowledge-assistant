# data

| 路徑 | 內容 |
|---|---|
| `manifest.csv` | 匯入清單：檔案、文件名稱、所屬部門、等級、版本、生效日、來源。`python -m scripts.import_docs` 依此匯入 |
| `raw/laws/` | 法規全文，由 `python -m scripts.fetch_laws` 從全國法規資料庫擷取，檔頭記錄修正日期與擷取日期 |
| `raw/mock/` | 為示範自行撰寫的模擬內部文件，非任何公司的真實規定。部門與等級刻意分散，用來測試權限 |
| `eval_cases.csv` | 評測題目。`expected_article` 可寫子條號，例如 `22-1`；`should_refuse=true` 表示文件中沒有答案 |
| `uploads/` | 經 API 上傳的檔案，檔名是內容的 SHA-256（不進版本控制） |

評測題目分三類，由系統自動判斷：

- 應回答：預期文件提問者看得到
- 應拒答：`should_refuse=true`
- 越權：預期文件提問者沒有權限，檢查回答中不可出現該文件

修改文件或題目後，請重新執行 `python -m scripts.load_eval_cases --reset` 與 `python -m scripts.run_eval`。
