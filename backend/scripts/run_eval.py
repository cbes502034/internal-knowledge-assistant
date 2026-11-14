"""在終端機執行評測並印出比較表（Markdown 格式，可以直接貼進文件）。

執行（在 backend/ 下）：
  python -m scripts.run_eval                                          目前的設定
  python -m scripts.run_eval --modes vector hybrid keyword            比較三種檢索方式
  python -m scripts.run_eval --modes hybrid --weights 1.0 0.5 0.3     比較 RRF 中關鍵字的權重
  python -m scripts.run_eval --thresholds 0.5 0.56 0.6                校準拒答門檻
  python -m scripts.run_eval --failures                               另外列出失敗案例
"""
import argparse
import itertools

from app.db import SessionLocal
from app.services import eval as eval_service

COLUMNS = [("hit_at_1", "Hit@1"), ("hit_at_3", "Hit@3"), ("mrr", "MRR"), ("false_refusal_rate", "誤拒率"),
           ("refuse_accuracy", "拒答正確率"), ("permission_pass", "越權通過"), ("leaks", "外洩"),
           ("p50_ms", "p50 ms"), ("p95_ms", "p95 ms")]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", default=[None])
    parser.add_argument("--weights", nargs="+", type=float, default=[None], help="RRF 中關鍵字排名的權重")
    parser.add_argument("--thresholds", nargs="+", type=float, default=[None])
    parser.add_argument("--failures", action="store_true")
    args = parser.parse_args()

    print("| 檢索方式 | 關鍵字權重 | 門檻 | " + " | ".join(label for _, label in COLUMNS) + " |")
    print("|---|---|---|" + "---|" * len(COLUMNS))
    for mode, weight, threshold in itertools.product(args.modes, args.weights, args.thresholds):
        with SessionLocal() as db:
            run = eval_service.create_run(db, mode=mode, threshold=threshold, keyword_weight=weight)
        eval_service.execute_run(run.id)
        with SessionLocal() as db:
            item = next(i for i in eval_service.list_runs(db, limit=100, offset=0)[0] if i["id"] == run.id)
            metrics, cfg = item["metrics"], item["config"]
            cells = [f"{metrics[key]:.0%}" if isinstance(metrics[key], float) else str(metrics[key])
                     for key, _ in COLUMNS]
            shown_weight = cfg["keyword_weight"] if cfg["mode"] == "hybrid" else "—"
            print(f"| {cfg['mode']} | {shown_weight} | {cfg['threshold']} | " + " | ".join(cells) + " |")
            if args.failures:
                for r in eval_service.list_results(db, run_id=run.id, failed_only=True):
                    print(f"    ✗ [{r['kind']}] {r['question']}｜應為 {r['expected']}｜實際第一名 {r['top_hit']}"
                          f"｜名次 {r['hit_rank']}｜拒答 {r['refused']}")


if __name__ == "__main__":
    main()
