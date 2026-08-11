"""Add durable RabbitMQ document import tasks.

Revision ID: 20260811_0004
Revises: 20260810_0003
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260811_0004"
down_revision: str | Sequence[str] | None = "20260810_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(150), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(30), server_default="queued", nullable=False),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("notes.id"), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    for name in ("id", "owner_id", "status", "available_at", "published_at"):
        op.create_index(f"ix_document_import_jobs_{name}", "document_import_jobs", [name])


def downgrade() -> None:
    op.drop_table("document_import_jobs")
