"""Record the existing application schema as the migration baseline.

Revision ID: 0001_existing_schema
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0001_existing_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    if "agents" not in existing:
        op.create_table(
            "agents",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agents_email", "agents", ["email"], unique=True)

    existing = set(inspect(op.get_bind()).get_table_names())
    if "posts" not in existing:
        op.create_table(
            "posts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_posts_agent_id", "posts", ["agent_id"], unique=False)
        op.create_index(
            "ix_posts_created_at_id",
            "posts",
            ["created_at", "id"],
            unique=False,
        )

    existing = set(inspect(op.get_bind()).get_table_names())
    if "comments" not in existing:
        op.create_table(
            "comments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_comments_agent_id", "comments", ["agent_id"], unique=False)
        op.create_index("ix_comments_post_id", "comments", ["post_id"], unique=False)
        op.create_index(
            "ix_comments_post_created_at",
            "comments",
            ["post_id", "created_at"],
            unique=False,
        )

    existing = set(inspect(op.get_bind()).get_table_names())
    if "post_matches" not in existing:
        op.create_table(
            "post_matches",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("agent_name", sa.String(length=120), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("match_method", sa.String(length=40), nullable=False),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "post_id",
                "agent_id",
                name="uq_post_matches_post_agent",
            ),
        )
        op.create_index(
            "ix_post_matches_agent_id",
            "post_matches",
            ["agent_id"],
            unique=False,
        )
        op.create_index(
            "ix_post_matches_post_id",
            "post_matches",
            ["post_id"],
            unique=False,
        )

    existing = set(inspect(op.get_bind()).get_table_names())
    if "notifications" not in existing:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("comment_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=False),
            sa.Column(
                "is_read",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_notifications_agent_id",
            "notifications",
            ["agent_id"],
            unique=False,
        )
        op.create_index(
            "ix_notifications_post_id",
            "notifications",
            ["post_id"],
            unique=False,
        )
        op.create_index(
            "ix_notifications_agent_read_created",
            "notifications",
            ["agent_id", "is_read", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    pass
