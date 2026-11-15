"""
【檔案用途】評測 API（只有 IT 管理員）：列出批次、執行一次評測、查看某批次的每題結果。

端點：
  GET  /api/v1/eval-runs                         批次列表（新的在前）
  POST /api/v1/eval-runs                         執行評測：回 202，題目在背景逐題跑
  GET  /api/v1/eval-runs/{run_id}/results        每題結果；?failed_only=true 只看失敗的
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.evaluation import EvalResult, EvalRun
from app.models.user import User, UserRole
from app.schemas.common import Page
from app.schemas.evaluation import EvalResultResponse, EvalRunResponse
from app.services import evaluation
from app.services.audit import log_event

router = APIRouter(prefix="/api/v1/eval-runs", tags=["evaluation"])

admin_only = require_role(UserRole.IT_ADMIN)


@router.get("", response_model=Page[EvalRunResponse])
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    total = db.scalar(select(func.count()).select_from(EvalRun))
    items = db.scalars(select(EvalRun).order_by(EvalRun.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)


@router.post("", response_model=EvalRunResponse, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """執行一次評測：每題都要呼叫模型，會跑一陣子，所以和上傳文件一樣回 202、在背景跑。"""
    try:
        run = evaluation.start_run(db)
    except evaluation.EvalAlreadyRunningError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    background.add_task(evaluation.run_in_background, run.id)
    log_event(db, request, "eval.run", user_id=admin.id, target=f"eval_run:{run.id}")
    return run


@router.get("/{run_id}/results", response_model=list[EvalResultResponse])
def list_results(
    run_id: int,
    failed_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """每題結果，依題號排序；failed_only=true 只留失敗的題目（失敗分析用）。"""
    if db.get(EvalRun, run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "評測批次不存在")
    results = db.scalars(select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.case_no)).all()
    if failed_only:
        results = [r for r in results if evaluation.is_failure(r)]
    return results
