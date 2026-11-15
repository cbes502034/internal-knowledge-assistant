"""
【檔案用途】RAG 評測：用固定題庫（backend/data/eval_cases.json）量出檢索與拒答的品質。
對應職缺：LLM／RAG 應用開發。面試常被問「你怎麼知道你的 RAG 好不好？」——答案就是這個檔案。

每一題的流程和真正問答完全一樣（共用 rag.py 的 should_refuse、build_prompt）：
  以題目指定的部門／角色身分 → 嵌入問題 → 混合檢索（含權限過濾）→ 拒答判斷 → 沒拒答就生成回答

題目分三類：
  answer      應該回答：檢查標準答案的條文排第幾（Hit@1、Hit@3、MRR）
  refuse      題庫外的問題：應該拒答
  permission  問的是自己沒權限的文件：應該拒答（同時驗證權限過濾）

指標：
  Hit@1 / Hit@3   標準答案排第 1 名／前 3 名的比例（只算 answer 題）
  MRR             標準答案名次倒數的平均（第 1 名 = 1、第 2 名 = 0.5、沒找到 = 0）
  拒答正確率       「該拒答就拒答、該回答就不拒答」的比例（全部題目）
  p50 / p95       回應時間的中位數與第 95 百分位（含生成）

被誰呼叫：routers/evaluation.py（管理介面按「執行評測」）、scripts/run_eval.py（命令列）。
"""

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm_service import LLMService
from app.core.retriever import Hit, hybrid_search
from app.models.department import Department
from app.models.evaluation import EvalResult, EvalRun
from app.models.user import User
from app.services import ingestion  # 借用 ingestion.session_scope：背景工作自己開 session（測試時會被換掉）
from app.services.rag import MIN_SIMILARITY, TOP_K, build_prompt, should_refuse

logger = logging.getLogger(__name__)

# 題庫位置：backend/data/eval_cases.json（這個檔案在 backend/app/services/，往上兩層是 backend）
CASES_PATH = Path(__file__).resolve().parents[2] / "data" / "eval_cases.json"


class EvalAlreadyRunningError(Exception):
    """已經有一個批次在跑：同時跑兩個會搶模型資源，數字也會互相干擾。"""


def load_cases(path: Path | None = None) -> list[dict]:
    """讀題庫 JSON。每題至少要有 question、kind、as_dept；answer 題還要有標準答案。"""
    cases = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    for no, case in enumerate(cases, start=1):
        if case["kind"] not in ("answer", "refuse", "permission"):
            raise ValueError(f"第 {no} 題的 kind 不正確：{case['kind']}")
        if case["kind"] == "answer" and not (case.get("expected_doc_title") and case.get("expected_article_no")):
            raise ValueError(f"第 {no} 題是 answer 題，但沒有標準答案")
    return cases


def find_rank(hits: list[Hit], doc_title: str, article_no: str) -> int | None:
    """標準答案（某文件的某一條）在檢索結果裡排第幾，1 開始；沒找到回傳 None。"""
    for rank, hit in enumerate(hits, start=1):
        if hit.doc_title == doc_title and hit.article_no == article_no:
            return rank
    return None


def percentile(values: list[int], p: float) -> int:
    """最近排名法的百分位數：排序後取第 ceil(p% × 筆數) 筆。p50 是中位數，p95 代表「95% 的請求都比它快」。"""
    if not values:
        return 0
    ordered = sorted(values)
    index = max(math.ceil(p / 100 * len(ordered)), 1) - 1
    return ordered[index]


def is_failure(result: EvalResult) -> bool:
    """這一題算不算失敗：該回答的沒排第一或被拒答；該拒答的沒拒答。"""
    if result.kind == "answer":
        return result.refused or result.hit_rank != 1
    return not result.refused


def model_declined(result: EvalResult) -> bool:
    """門檻沒擋下（有生成回答），但模型依 prompt 自己回答「找不到依據」：第二道防線。"""
    return result.answer is not None and "找不到依據" in result.answer


def compute_metrics(results: list[EvalResult]) -> dict:
    """把每題結果彙總成指標。answer 題才算檢索指標；拒答正確率看全部題目。"""
    answerable = [r for r in results if r.kind == "answer"]
    n = len(answerable)
    latencies = [r.latency_ms for r in results]

    def ratio(count: int, total: int) -> float:
        return round(count / total, 4) if total else 0.0

    return {
        "cases": len(results),
        "answerable": n,
        "hit_at_1": ratio(sum(r.hit_rank == 1 for r in answerable), n),
        "hit_at_3": ratio(sum(r.hit_rank is not None and r.hit_rank <= 3 for r in answerable), n),
        "mrr": round(sum(1 / r.hit_rank for r in answerable if r.hit_rank) / n, 4) if n else 0.0,
        "refuse_accuracy": ratio(sum(r.refused == (r.kind != "answer") for r in results), len(results)),
        # 兩種拒答錯誤分開數：誤拒（該答卻拒答，使用者覺得沒用）、漏拒（該拒卻回答，可能亂答或越權）
        "false_refusals": sum(r.kind == "answer" and r.refused for r in results),
        "missed_refusals": sum(r.kind != "answer" and not r.refused for r in results),
        # 第二道防線的效果：漏拒的題目裡，有幾題模型自己回答「找不到依據」（好事）；
        # 反過來，應回答的題目被模型說找不到依據（壞事：檢索到了，模型卻不肯答）
        "missed_refusals_caught_by_prompt": sum(r.kind != "answer" and not r.refused and model_declined(r) for r in results),
        "answers_declined_by_model": sum(r.kind == "answer" and not r.refused and model_declined(r) for r in results),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
    }


def start_run(db: Session) -> EvalRun:
    """建立一個 running 的批次並 commit；真正的評測交給背景執行 run_evaluation。"""
    if db.scalar(select(EvalRun.id).where(EvalRun.status == "running")) is not None:
        raise EvalAlreadyRunningError("已有評測正在執行")

    run = EvalRun(
        embed_model=settings.embed_model,
        config={
            "chat_model": settings.chat_model,
            "top_k": TOP_K,
            "min_similarity": MIN_SIMILARITY,
            "retrieval": "hybrid (vector + BM25, RRF)",
        },
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_evaluation(db: Session, run_id: int, llm: LLMService | None = None, cases_path: Path | None = None) -> EvalRun:
    """逐題執行並寫入結果，最後算指標、標成 done；任何一步失敗就整批標成 failed 並記下原因。"""
    llm = llm or LLMService(
        settings.ollama_base_url,
        settings.embed_model,
        settings.chat_model,
        timeout=settings.llm_timeout,
    )
    run = db.get(EvalRun, run_id)
    if run is None:
        raise LookupError(f"評測批次 {run_id} 不存在")

    try:
        cases = load_cases(cases_path)
        dept_ids = dict(db.execute(select(Department.code, Department.id)).all())  # {部門代碼: 編號}

        results = []
        for case_no, case in enumerate(cases, start=1):
            if case["as_dept"] not in dept_ids:
                raise ValueError(f"第 {case_no} 題的部門代碼不存在：{case['as_dept']}")

            # 用「題目指定的身分」提問：不存進資料庫的臨時 User 物件，權限過濾只看 dept_id 與 role
            asker = User(dept_id=dept_ids[case["as_dept"]], role=case.get("as_role", "employee"))
            question = case["question"]

            started = time.perf_counter()
            hits = hybrid_search(db, question, llm.embed(question), asker, k=TOP_K)
            refused = should_refuse(hits)  # 和真正問答同一套拒答規則
            answer = None
            if not refused:
                prompt, _ = build_prompt(question, hits)
                answer = llm.generate(prompt)
            latency_ms = int((time.perf_counter() - started) * 1000)

            expected_title = case.get("expected_doc_title")
            expected_article = case.get("expected_article_no")
            results.append(
                EvalResult(
                    run_id=run_id,
                    case_no=case_no,
                    question=question,
                    kind=case["kind"],
                    expected=f"{expected_title} {expected_article}" if expected_title else None,
                    hit_rank=find_rank(hits, expected_title, expected_article) if case["kind"] == "answer" else None,
                    refused=refused,
                    top_hit=f"{hits[0].doc_title} {hits[0].article_no}" if hits else None,
                    answer=answer,
                    latency_ms=latency_ms,
                )
            )

        db.add_all(results)
        run.metrics = compute_metrics(results)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        # 和入庫一樣：先 rollback 丟掉做到一半的結果，再把批次標成 failed，保留失敗原因
        db.rollback()
        db.execute(
            update(EvalRun)
            .where(EvalRun.id == run_id)
            .values(status="failed", error=str(e)[:500], finished_at=datetime.now(timezone.utc))
        )
        db.commit()
        raise

    return run


def run_in_background(run_id: int) -> None:
    """給 FastAPI BackgroundTasks 呼叫的入口：自己開 session；例外沒人接，所以在這裡記日誌。"""
    with ingestion.session_scope() as db:
        try:
            run_evaluation(db, run_id)
        except Exception:
            logger.exception("評測批次 %s 失敗，已標記為 failed", run_id)


def mark_interrupted_runs(db: Session) -> int:
    """伺服器啟動時呼叫：上次關機時還在跑的批次永遠不會跑完，標成 failed。回傳筆數。"""
    result = db.execute(
        update(EvalRun)
        .where(EvalRun.status == "running")
        .values(status="failed", error="伺服器重啟，評測中斷", finished_at=datetime.now(timezone.utc))
    )
    db.commit()
    return result.rowcount
