"""login lockout, sub-articles, window chunking, eval details

Revision ID: 3c1f5a2b7d90
Revises: 97be1df50141
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3c1f5a2b7d90"
down_revision: Union[str, None] = "97be1df50141"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 登入鎖定
    op.add_column("users", sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    # 文件切塊方式：依條（article）或滑動視窗（window）
    op.add_column("documents", sa.Column("chunk_mode", sa.String(length=10), server_default="article", nullable=False))
    op.create_check_constraint("ck_documents_chunk_mode", "documents", "chunk_mode IN ('article', 'window')")

    # 子條號：第 15-1 條 → article_no=15、sub_no=1；唯一鍵加入 sub_no
    op.add_column("chunks", sa.Column("sub_no", sa.SmallInteger(), server_default="0", nullable=False))
    op.drop_constraint("uq_chunks_document_article", "chunks", type_="unique")
    op.create_unique_constraint("uq_chunks_document_article_sub", "chunks", ["document_id", "article_no", "sub_no"])

    # 出處的顯示文字快照
    op.add_column("message_citations", sa.Column("locator", sa.String(length=20), nullable=True))

    # 評測：子條號、題目類型、越權檢查、失敗分析
    op.add_column("eval_cases", sa.Column("expected_sub_no", sa.SmallInteger(), server_default="0", nullable=False))
    op.add_column("eval_results", sa.Column("kind", sa.String(length=12), server_default="answer", nullable=False))
    op.add_column("eval_results", sa.Column("leaked", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("eval_results", sa.Column("top_hit", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_results", "top_hit")
    op.drop_column("eval_results", "leaked")
    op.drop_column("eval_results", "kind")
    op.drop_column("eval_cases", "expected_sub_no")
    op.drop_column("message_citations", "locator")
    op.drop_constraint("uq_chunks_document_article_sub", "chunks", type_="unique")
    op.create_unique_constraint("uq_chunks_document_article", "chunks", ["document_id", "article_no"])
    op.drop_column("chunks", "sub_no")
    op.drop_constraint("ck_documents_chunk_mode", "documents", type_="check")
    op.drop_column("documents", "chunk_mode")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_logins")
