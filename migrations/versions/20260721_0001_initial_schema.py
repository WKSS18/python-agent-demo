"""Create the initial application schema.

Revision ID: 20260721_0001
Revises: None
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create users, notes, agent sessions, and agent messages."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_id", "notes", ["id"], unique=False)
    op.create_index("ix_notes_owner_id", "notes", ["owner_id"], unique=False)
    op.create_index("ix_notes_title", "notes", ["title"], unique=False)

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_sessions_id", "agent_sessions", ["id"], unique=False)
    op.create_index("ix_agent_sessions_owner_id", "agent_sessions", ["owner_id"], unique=False)

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_messages_id", "agent_messages", ["id"], unique=False)
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"], unique=False)


def downgrade() -> None:
    """Drop all application tables in reverse dependency order."""
    # MySQL removes a table's indexes and foreign keys with the table. Dropping
    # an FK-backed index first fails because the still-present FK requires it.
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
    op.drop_table("notes")
    op.drop_table("users")
