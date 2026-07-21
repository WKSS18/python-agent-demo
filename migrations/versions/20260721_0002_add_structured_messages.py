"""为 Agent 消息增加类型和 JSON 数据，以支持表单、引用及附件。

Revision ID: 20260721_0002
Revises: 20260721_0001
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0002"
down_revision: str | Sequence[str] | None = "20260721_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增兼容旧文本消息的结构化字段。"""
    # server_default 让历史消息在加列时自动归类为普通文本消息。
    op.add_column(
        "agent_messages",
        sa.Column("message_type", sa.String(length=20), server_default="text", nullable=False),
    )
    op.add_column(
        "agent_messages",
        sa.Column("message_data", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回滚结构化消息字段。"""
    op.drop_column("agent_messages", "message_data")
    op.drop_column("agent_messages", "message_type")
