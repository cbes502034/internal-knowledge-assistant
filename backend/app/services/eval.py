"""評測：用固定測試題衡量檢索與拒答的表現（對應企劃書 第 13 節）。"""
from sqlalchemy.orm import Session

from app.models import EvalRun


def compute_metrics(results: list[dict]) -> dict:
    """TODO：由逐題結果算出指標。這是純函式，先寫它，tests/spec/test_metrics.py 有規格。

    results 每筆：{"hit_rank": int | None, "should_refuse": bool, "refused": bool, "latency_ms": int}

    - hit_at_1、hit_at_3：只算「應該有答案」的題目（should_refuse=False）
        hit_at_k = hit_rank 不為 None 且 <= k 的題數 ÷ 題數
    - mrr：同一批題目，每題取 1/hit_rank（未命中算 0），再平均
    - refuse_accuracy：只算 should_refuse=True 的題目，refused=True 的比例
    - p50_ms、p95_ms：全部題目的耗時分位數
        提示：排序後取索引 ceil(p * n) - 1
    - 沒有題目的類別回 0.0，不要除以零
    """
    raise NotImplementedError("services.eval.compute_metrics 尚未實作")


def run(db: Session, *, embed_model: str | None, config: dict | None) -> EvalRun:
    """TODO：執行一次評測。

    1. 建立 EvalRun（embed_model 預設取 settings.embed_model；config 記下 top_k、門檻等）
    2. 取出全部 EvalCase；每題：
         a. 以 case.as_dept、case.as_role 組出「模擬使用者」（不寫入資料庫）
         b. hits = retriever.hybrid_search(db, question=case.question, user=模擬使用者, k=...)
         c. hit_rank = 正確段落（expected_doc_title + expected_article_no）在 hits 中的名次，沒有則 None
         d. refused = hits 為空或最高分低於門檻
         e. 記錄耗時，寫入 EvalResult
    3. 填 finished_at、commit
    備註：這裡只評「檢索與拒答」，不呼叫生成模型，所以跑得快、結果穩定
    """
    raise NotImplementedError("services.eval.run 尚未實作")


def list_runs(db: Session, *, limit: int, offset: int) -> tuple[list, int]:
    """TODO：評測批次列表（新的在前），每筆附上 compute_metrics 的結果。"""
    raise NotImplementedError("services.eval.list_runs 尚未實作")


def list_results(db: Session, *, run_id: int, failed_only: bool) -> list:
    """TODO：某批次的逐題結果；failed_only=True 時只回失敗案例。

    失敗的定義：應有答案卻沒進前 3 名；或應拒答卻沒拒答；或不該拒答卻拒答。
    """
    raise NotImplementedError("services.eval.list_results 尚未實作")
