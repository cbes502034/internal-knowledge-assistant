from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_it_admin
from app.models import User
from app.schemas import DocumentDetailOut, DocumentOut, DocumentPatch, Page
from app.services import document as document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=Page[DocumentOut])
def list_documents(
    status: str | None = Query(default=None),
    dept: str | None = Query(default=None, description="部門代碼"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    items, total = document_service.list_documents(db, status=status, dept_code=dept, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=DocumentOut, status_code=202)
def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=255),
    dept_code: str = Form(...),
    level: Literal["public", "dept", "restricted"] = Form(default="public"),
    version: str = Form(default="v1", max_length=30),
    effective_date: date | None = Form(default=None),
    source: str | None = Form(default=None, max_length=500),
    admin: User = Depends(require_it_admin),
    db: Session = Depends(get_db),
):
    """上傳文件（202：已受理），切塊與向量化在背景執行。"""
    limit = get_settings().max_upload_mb * 1024 * 1024
    document = document_service.upload(
        db, actor=admin, filename=file.filename or "", data=file.file.read(limit + 1), title=title, dept_code=dept_code,
        level=level, version=version, effective_date=effective_date, source=source)
    background.add_task(document_service.process_in_background, document.id)
    return document


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: int, _: User = Depends(require_it_admin), db: Session = Depends(get_db)):
    return document_service.get_detail(db, document_id=document_id)


@router.patch("/{document_id}", response_model=DocumentOut)
def patch_document(document_id: int, body: DocumentPatch, admin: User = Depends(require_it_admin),
                   db: Session = Depends(get_db)):
    """修改等級或作廢。"""
    return document_service.update(db, actor=admin, document_id=document_id, patch=body)


@router.post("/{document_id}/processing-jobs", response_model=DocumentOut, status_code=202)
def reprocess_document(document_id: int, background: BackgroundTasks, admin: User = Depends(require_it_admin),
                       db: Session = Depends(get_db)):
    """重新處理：清除舊段落後重新切塊、向量化（背景執行）。"""
    document = document_service.request_reprocess(db, actor=admin, document_id=document_id)
    background.add_task(document_service.process_in_background, document.id)
    return document
