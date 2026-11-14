from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_it_admin
from app.models import User
from app.schemas import EvalResultOut, EvalRunCreate, EvalRunOut, Page
from app.services import eval as eval_service

router = APIRouter(prefix="/eval-runs", tags=["eval"])


@router.post("", response_model=EvalRunOut, status_code=202)
def create_run(body: EvalRunCreate, background: BackgroundTasks, _: User = Depends(require_it_admin),
               db: Session = Depends(get_db)):
    """執行一次評測（背景執行；查詢列表時 finished_at 有值就是完成了）。"""
    run = eval_service.create_run(db, mode=body.mode, top_k=body.top_k, threshold=body.threshold,
                                  keyword_weight=body.keyword_weight)
    background.add_task(eval_service.execute_run, run.id)
    return {"id": run.id, "embed_model": run.embed_model, "config": run.config,
            "started_at": run.started_at, "finished_at": None, "error": None, "metrics": None}


@router.get("", response_model=Page[EvalRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    items, total = eval_service.list_runs(db, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{run_id}/results", response_model=list[EvalResultOut])
def list_results(
    run_id: int,
    failed_only: bool = Query(default=False, description="只看失敗案例"),
    _: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    return eval_service.list_results(db, run_id=run_id, failed_only=failed_only)
