"""評測：測試題、評測批次、逐題結果。"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Identity, Integer, SmallInteger,
                        String, Text, UniqueConstraint, false, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class EvalCase(Base):
    """評測用的固定題目與標準答案。"""
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    expected_doc_title: Mapped[str | None] = mapped_column(String(255))   # 無答案題為空
    expected_article_no: Mapped[int | None] = mapped_column(Integer)
    expected_sub_no: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    as_dept: Mapped[str] = mapped_column(String(20))                # 以哪個部門身分提問（越權測試用）
    as_role: Mapped[str] = mapped_column(String(20), default="employee")
    should_refuse: Mapped[bool] = mapped_column(Boolean, default=False)


class EvalRun(Base):
    """一次評測的設定，用來比較不同檢索方式與參數。"""
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    embed_model: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict | None] = mapped_column(JSONB)              # mode、top_k、threshold
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalResult(Base):
    """某批次對某題的結果（批次與測試題的多對多中介表）。"""
    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_eval_results_run_case"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"))
    kind: Mapped[str] = mapped_column(String(12), default="answer", server_default="answer")  # answer／refuse／permission
    hit_rank: Mapped[int | None] = mapped_column(SmallInteger)      # 正確段落的名次；未命中為空
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    leaked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # 是否出現無權限的段落
    top_hit: Mapped[str | None] = mapped_column(String(300))        # 實際第一名，失敗分析用
    latency_ms: Mapped[int | None] = mapped_column(Integer)
