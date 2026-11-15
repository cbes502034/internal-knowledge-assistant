"""
【檔案用途】在命令列跑一次 RAG 評測（和管理介面按「執行評測」一樣，結果也會存進資料庫），並印出指標與失敗題目。
需要 Ollama 在跑，且資料庫裡要有文件（例如先執行 python -m scripts.import_samples）。

用法（在 backend 目錄）：
    python -m scripts.run_eval
"""

import app.models  # noqa: F401  確保所有 model 都已登記
from app.core.database import SessionLocal
from app.services.evaluation import is_failure, run_evaluation, start_run


def main() -> None:
    with SessionLocal() as db:
        run = start_run(db)
        print(f"評測批次 #{run.id} 開始（每題都會呼叫模型，需要一點時間）…")
        run = run_evaluation(db, run.id)

        m = run.metrics
        print(f"\n共 {m['cases']} 題（應回答 {m['answerable']} 題）")
        print(f"Hit@1 {m['hit_at_1']:.1%}   Hit@3 {m['hit_at_3']:.1%}   MRR {m['mrr']:.2f}")
        print(f"拒答正確率 {m['refuse_accuracy']:.1%}（誤拒 {m['false_refusals']} 題、漏拒 {m['missed_refusals']} 題）")
        print(f"漏拒的題目中，模型依 prompt 自己回答「找不到依據」：{m['missed_refusals_caught_by_prompt']} 題")
        print(f"應回答卻被模型說找不到依據：{m['answers_declined_by_model']} 題")
        print(f"回應時間 p50 {m['p50_ms'] / 1000:.2f} 秒、p95 {m['p95_ms'] / 1000:.2f} 秒")

        failures = [r for r in run.results if is_failure(r)]
        if failures:
            print("\n失敗的題目：")
            for r in failures:
                print(f"  #{r.case_no} [{r.kind}] {r.question}")
                print(f"      標準答案：{r.expected or '應拒答'}；實際第一名：{r.top_hit or '無'}；名次：{r.hit_rank or '—'}；拒答：{'是' if r.refused else '否'}")


if __name__ == "__main__":
    main()
