"""Add daily AI note reviews.

Revision ID: 20260918_0006
Revises: 20260821_0005
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260918_0006"
down_revision: str | Sequence[str] | None = "20260821_0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "note_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("review_date", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_points", sa.JSON(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("todo_items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.UniqueConstraint("owner_id", "note_id", "review_date", name="uq_note_reviews_owner_note_date"),
    )
    op.create_index("ix_note_reviews_owner_id", "note_reviews", ["owner_id"])
    op.create_index("ix_note_reviews_note_id", "note_reviews", ["note_id"])
    op.create_index("ix_note_reviews_review_date", "note_reviews", ["review_date"])

def downgrade() -> None:
    op.drop_table("note_reviews")
