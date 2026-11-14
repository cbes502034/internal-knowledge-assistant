"""評測：用固定測試題衡量檢索、拒答與權限（對應企劃書 第 13 節）。

只評「檢索與拒答」，不呼叫生成模型：跑得快、結果穩定，改一個參數就能比較前後差異。
"""
import math
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import retriever
from app.core.llm_service import get_llm
from app.db import SessionLocal
from app.errors import not_found
from app.models import Department, Document, EvalCase, EvalResult, EvalRun

EVAL_K = 5     # 每題取前幾名來找正確段落


def _ratio(numerator: int | float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _kind(result: dict) -> str:
    return result.get("kind") or ("refuse" if result["should_refuse"] else "answer")


def compute_metrics(results: list[dict]) -> dict:
    """由逐題結果算出指標（純函式）。

    題目分三類：
      answer     應該找得到答案：算 Hit@1、Hit@3、MRR、誤拒率
      refuse     文件裡沒有答案：算拒答正確率
      permission 答案在使用者沒權限的文件：算越權測試通過率（不可出現沒權限的段落）
    """
    answer = [r for r in results if _kind(r) == "answer"]
    refuse = [r for r in results if _kind(r) == "refuse"]
    permission = [r for r in results if _kind(r) == "permission"]

    def hit_at(k: int) -> float:
        return _ratio(sum(1 for r in answer if r["hit_rank"] is not None and r["hit_rank"] <= k), len(answer))

    latencies = sorted(r["latency_ms"] for r in results if r.get("latency_ms") is not None)

    def percentile(p: float) -> int:
        return latencies[max(0, math.ceil(p * len(latencies)) - 1)] if latencies else 0

    return {
        "cases": len(results),
        "hit_at_1": hit_at(1),
        "hit_at_3": hit_at(3),
        "mrr": _ratio(sum(1 / r["hit_rank"] for r in answer if r["hit_rank"]), len(answer)),
        "false_refusal_rate": _ratio(sum(1 for r in answer if r.get("refused")), len(answer)),
        "refuse_accuracy": _ratio(sum(1 for r in refuse if r["refused"]), len(refuse)),
        "permission_pass": _ratio(sum(1 for r in permission if not r.get("leaked")), len(permission)),
        "leaks": sum(1 for r in results if r.get("leaked")),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
    }


def can_view(document: Document, dept_id: int | None, role: str) -> bool:
    """權限規則的 Python 版本，和檢索 SQL 分開實作：用來獨立驗證 SQL 沒有放出不該看的段落。"""
    if document.status != "ready":
        return False
    if document.level == "public":
        return True
    if document.level == "dept":
        return document.dept_id == dept_id
    return document.dept_id == dept_id and role == "manager"


def create_run(db: Session, *, mode: str | None = None, top_k: int | None = None,
               threshold: float | None = None, keyword_weight: float | None = None) -> EvalRun:
    """建立評測批次；沒指定的參數都用目前的設定值，所以「預設設定」本身也能被評測。"""
    settings = get_settings()
    run = EvalRun(embed_model=get_llm().embed_model, config={
        "mode": mode or settings.search_mode,
        "top_k": top_k or EVAL_K,
        "threshold": settings.score_threshold if threshold is None else threshold,
        "keyword_weight": settings.keyword_weight if keyword_weight is None else keyword_weight,
    })
    db.add(run)
    db.commit()
    return run


def execute_run(run_id: int) -> None:
    """逐題檢索並寫入結果（背景工作，自己開連線）。"""
    with SessionLocal() as db:
        run = db.get(EvalRun, run_id)
        if run is None:
            return
        cfg = run.config
        mode, k, threshold = cfg["mode"], cfg["top_k"], cfg["threshold"]
        dept_ids = {d.code: d.id for d in db.scalars(select(Department))}
        documents = list(db.scalars(select(Document)))
        by_id = {d.id: d for d in documents}
        by_title = {d.title: d for d in documents if d.status == "ready"}
        retriever.clear_query_cache()        # 每個批次都從「沒有快取」開始，耗時才能互相比較
        retriever.warm_up(db)

        for case in db.scalars(select(EvalCase).order_by(EvalCase.id)):
            asker = SimpleNamespace(id=None, dept_id=dept_ids.get(case.as_dept), role=case.as_role)
            started = time.monotonic()
            hits = retriever.hybrid_search(db, question=case.question, user=asker, k=k, mode=mode,
                                           keyword_weight=cfg.get("keyword_weight"))
            latency_ms = int((time.monotonic() - started) * 1000)

            expected = by_title.get(case.expected_doc_title) if case.expected_doc_title else None
            if case.should_refuse:
                kind = "refuse"
            elif expected is not None and not can_view(expected, asker.dept_id, asker.role):
                kind = "permission"
            else:
                kind = "answer"
            hit_rank = next((rank for rank, hit in enumerate(hits, start=1)
                             if hit.doc_title == case.expected_doc_title
                             and hit.article_no == case.expected_article_no
                             and hit.sub_no == (case.expected_sub_no or 0)), None)
            db.add(EvalResult(
                run_id=run.id, case_id=case.id, kind=kind, hit_rank=hit_rank,
                refused=retriever.should_refuse(case.question, hits, threshold),
                leaked=any(not can_view(by_id[hit.document_id], asker.dept_id, asker.role) for hit in hits),
                top_hit=f"《{hits[0].doc_title}》{hits[0].locator}"[:300] if hits else None,
                latency_ms=latency_ms,
            ))
        run.finished_at = datetime.now(timezone.utc)
        db.commit()


def _result_dicts(db: Session, run_id: int) -> list[dict]:
    rows = db.execute(
        select(EvalResult, EvalCase).join(EvalCase, EvalCase.id == EvalResult.case_id)
        .where(EvalResult.run_id == run_id).order_by(EvalCase.id))
    return [{
        "case_id": case.id, "question": case.question, "kind": result.kind,
        "expected": (f"《{case.expected_doc_title}》第{case.expected_article_no}"
                     f"{'-' + str(case.expected_sub_no) if case.expected_sub_no else ''}條")
        if case.expected_doc_title else None,
        "as_dept": case.as_dept, "as_role": case.as_role,
        "should_refuse": case.should_refuse, "hit_rank": result.hit_rank, "refused": result.refused,
        "leaked": result.leaked, "top_hit": result.top_hit, "latency_ms": result.latency_ms,
    } for result, case in rows]


def _is_failure(r: dict) -> bool:
    if r["kind"] == "refuse":
        return not r["refused"]
    if r["kind"] == "permission":
        return r["leaked"]
    return r["hit_rank"] is None or r["hit_rank"] > 3 or r["refused"]


def list_runs(db: Session, *, limit: int, offset: int) -> tuple[list[dict], int]:
    total = db.scalar(select(func.count(EvalRun.id)))
    runs = db.scalars(select(EvalRun).order_by(EvalRun.id.desc()).limit(limit).offset(offset))
    items = []
    for run in runs:
        results = _result_dicts(db, run.id)
        items.append({
            "id": run.id, "embed_model": run.embed_model, "config": run.config,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "metrics": compute_metrics(results) if run.finished_at else None,
        })
    return items, total


def list_results(db: Session, *, run_id: int, failed_only: bool) -> list[dict]:
    if db.get(EvalRun, run_id) is None:
        raise not_found("找不到評測批次")
    results = _result_dicts(db, run_id)
    return [r for r in results if _is_failure(r)] if failed_only else results
