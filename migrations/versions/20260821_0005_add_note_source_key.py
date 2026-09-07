"""Add internal provenance key for idempotent generated note imports.

Revision ID: 20260821_0005
Revises: 20260811_0004
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0005"
down_revision: str | Sequence[str] | None = "20260811_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(sa.Column("source_key", sa.String(160), nullable=True))
        batch_op.create_unique_constraint(
            "uq_notes_owner_source_key",
            ["owner_id", "source_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_constraint("uq_notes_owner_source_key", type_="unique")
        batch_op.drop_column("source_key")
