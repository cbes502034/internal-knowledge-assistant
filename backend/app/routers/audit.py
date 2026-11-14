from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_it_admin
from app.models import User
from app.schemas import AuditLogOut, Page
from app.services import audit as audit_service

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def list_audit_logs(
    user_id: int | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    items, total = audit_service.list_logs(db, user_id=user_id, since=since, until=until,
                                           limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)
