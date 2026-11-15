"""
【檔案用途】評測的兩張資料表（ORM model）：
  - eval_runs：一次評測批次（用哪個模型、什麼參數、結果指標）。
  - eval_results：批次裡每一題的結果（正確答案排第幾、有沒有拒答、花多久）。

對應職缺：LLM／RAG 應用開發。RAG 好不好不能憑感覺，要用固定題庫量出數字（Hit@k、MRR、拒答正確率），
換模型或調參數之前之後各跑一次，才知道是變好還是變差。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB  # PostgreSQL 的 JSON 型別：參數與指標的欄位數量會變，用 JSON 存最彈性
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EvalRun(Base):
    """一次評測批次。"""
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="批次編號")

    # 狀態：running 跑到一半 / done 完成 / failed 失敗（例如模型服務掛了）
    status: Mapped[str] = mapped_column(
        String(10),
        default="running",
        server_default=text("'running'"),
        comment="running / done / failed",
    )

    # 記下當時用的模型與參數：之後比較兩個批次時，才知道差異是哪個設定造成的
    embed_model: Mapped[str] = mapped_column(String(100), comment="嵌入模型")
    config: Mapped[dict | None] = mapped_column(JSONB, comment="當時的參數：top_k、拒答門檻、生成模型…")

    # 指標：hit_at_1、hit_at_3、mrr、refuse_accuracy、p50_ms、p95_ms…；跑完才有
    metrics: Mapped[dict | None] = mapped_column(JSONB, comment="評測指標")
    error: Mapped[str | None] = mapped_column(String(500), comment="失敗原因")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="開始時間",
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="結束時間")

    results: Mapped[list[EvalResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EvalResult.case_no",
    )

    __table_args__ = (
        CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_eval_runs_status_valid"),
        {"comment": "評測批次"},
    )


class EvalResult(Base):
    """
    批次裡一題的結果。題目內容與標準答案也存一份（快照）：
    題庫檔案之後可能會改，但「這個批次當時考的是什麼」要能對得上。
    """
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="編號")

    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        index=True,
        comment="所屬批次",
    )

    # ── 題目（快照）──
    case_no: Mapped[int] = mapped_column(Integer, comment="題庫中的題號")
    question: Mapped[str] = mapped_column(Text, comment="問題")
    kind: Mapped[str] = mapped_column(String(12), comment="answer 應回答 / refuse 應拒答（題庫外）/ permission 應拒答（無權限）")
    expected: Mapped[str | None] = mapped_column(String(300), comment="標準答案：文件標題 條號；應拒答的題目為空")

    # ── 結果 ──
    hit_rank: Mapped[int | None] = mapped_column(SmallInteger, comment="標準答案在檢索結果排第幾（1 開始）；沒找到為空")
    refused: Mapped[bool] = mapped_column(Boolean, comment="系統是否拒答")
    top_hit: Mapped[str | None] = mapped_column(String(300), comment="實際排第一的是哪一條，失敗分析用")
    answer: Mapped[str | None] = mapped_column(Text, comment="模型產生的回答（人工檢查是否忠於條文用）；拒答時為空")
    latency_ms: Mapped[int] = mapped_column(Integer, comment="從收到問題到產生回答花了幾毫秒")

    run: Mapped[EvalRun] = relationship(back_populates="results")

    __table_args__ = (
        CheckConstraint("kind IN ('answer', 'refuse', 'permission')", name="ck_eval_results_kind_valid"),
        {"comment": "評測每題結果"},
    )
