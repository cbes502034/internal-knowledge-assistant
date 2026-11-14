"""依 data/manifest.csv 匯入文件並立即處理（切塊＋向量化）。

執行（在 backend/ 下）：python -m scripts.import_docs
- 已匯入且處理成功的檔案略過
- 已匯入但處理失敗（例如當時模型沒開）的檔案重新處理
需要 Ollama 已啟動並下載嵌入模型（ollama pull bge-m3）。
"""
import csv
import hashlib
from datetime import date

from sqlalchemy import select

from app.config import ROOT_DIR
from app.db import SessionLocal
from app.errors import AppError
from app.models import Document
from app.services import document as document_service

MANIFEST = ROOT_DIR / "data" / "manifest.csv"


def main() -> None:
    with MANIFEST.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with SessionLocal() as db:
        for row in rows:
            data = (ROOT_DIR / "data" / row["file"]).read_bytes()
            existing = db.scalar(select(Document).where(Document.checksum == hashlib.sha256(data).hexdigest()))
            if existing is not None and existing.status in ("ready", "deprecated"):
                print(f"略過 {existing.title}：已匯入（{existing.status}）")
                continue
            if existing is None:
                try:
                    existing = document_service.upload(
                        db, actor=None, filename=row["file"].rsplit("/", 1)[-1], data=data, title=row["title"],
                        dept_code=row["dept_code"], level=row["level"], version=row["version"],
                        effective_date=date.fromisoformat(row["effective_date"]) if row["effective_date"] else None,
                        source=row["source"] or None)
                except AppError as exc:
                    print(f"略過 {row['title']}：{exc.message}")
                    continue
            document = document_service.process(db, existing)
            print(f"{document.title} {document.version}：{document.status}（{document.chunk_mode}）")


if __name__ == "__main__":
    main()
