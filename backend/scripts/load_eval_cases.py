"""把 data/eval_cases.csv 載入 eval_cases 資料表。

執行（在 backend/ 下）：python -m scripts.load_eval_cases [--reset]
已有評測紀錄時，題目被引用中不能直接替換；加 --reset 會一併清除舊的評測批次與結果。
"""
import argparse
import csv
import sys

from sqlalchemy import delete, func, select

from app.config import ROOT_DIR
from app.db import SessionLocal
from app.models import EvalCase, EvalResult, EvalRun

CSV_PATH = ROOT_DIR / "data" / "eval_cases.csv"


def parse_article(value: str) -> tuple[int | None, int]:
    """'15-1' → (15, 1)；'2' → (2, 0)；空白 → (None, 0)"""
    if not value.strip():
        return None, 0
    main, _, sub = value.strip().partition("-")
    return int(main), int(sub or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清除舊的評測批次與結果")
    args = parser.parse_args()

    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with SessionLocal() as db:
        if db.scalar(select(func.count(EvalResult.id))) and not args.reset:
            sys.exit("已有評測結果；要替換題目請加 --reset（會清除舊的評測批次）")
        db.execute(delete(EvalResult))
        db.execute(delete(EvalRun))
        db.execute(delete(EvalCase))
        for row in rows:
            article_no, sub_no = parse_article(row["expected_article"])
            db.add(EvalCase(question=row["question"], expected_doc_title=row["expected_doc_title"] or None,
                            expected_article_no=article_no, expected_sub_no=sub_no, as_dept=row["as_dept"],
                            as_role=row["as_role"] or "employee",
                            should_refuse=row["should_refuse"].strip().lower() == "true"))
        db.commit()
        print(f"已載入 {len(rows)} 題")


if __name__ == "__main__":
    main()
