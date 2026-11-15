"""
【檔案用途】把示範文件（backend/data/sample_docs，全部是模擬資料）匯入資料庫，讓系統有東西可以回答。
走的是和管理員上傳完全相同的入庫流程（register_upload → process_document），需要 Ollama 在跑。
已匯入過的文件會因為 checksum 重複而略過，所以可以重複執行。

用法（在 backend 目錄）：
    python -m scripts.import_samples
"""

import json
import sys
from pathlib import Path

from sqlalchemy import func, select

import app.models  # noqa: F401  確保所有 model 都已登記
from app.core.database import SessionLocal
from app.models.department import Department
from app.models.document import DocumentChunk
from app.services.ingestion import DuplicateDocumentError, process_document, register_upload

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample_docs"


def main() -> None:
    manifest = json.loads((SAMPLE_DIR / "manifest.json").read_text(encoding="utf-8"))

    with SessionLocal() as db:
        dept_ids = dict(db.execute(select(Department.code, Department.id)).all())
        if not dept_ids:
            sys.exit("資料庫沒有部門資料，請先執行 python -m scripts.seed_departments")

        for item in manifest:
            raw = (SAMPLE_DIR / item["file"]).read_bytes()
            try:
                document = register_upload(
                    db,
                    filename=item["file"],
                    raw=raw,
                    dept_id=dept_ids[item["dept_code"]],
                    title=item["title"],
                    version=item["version"],
                    level=item["level"],
                    source="模擬資料",
                )
            except DuplicateDocumentError as e:
                print(f"略過 {item['title']}：已存在（編號 {e.existing_id}）")
                continue

            process_document(db, document.id)  # 這裡直接同步處理，不經過背景工作
            chunks = db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document.id))
            print(f"已匯入 {item['title']}（{item['level']}，{item['dept_code']}）：{chunks} 個 chunk")


if __name__ == "__main__":
    main()
