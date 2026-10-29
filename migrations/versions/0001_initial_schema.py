"""Initial news queue and daily API usage.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("source_name", sa.String(length=250), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_summary", sa.Text(), nullable=False),
        sa.Column("published_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_title", sa.Text(), nullable=True),
        sa.Column("generated_body", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("photo_query", sa.String(length=300), nullable=True),
        sa.Column("photo_url", sa.String(length=2048), nullable=True),
        sa.Column("photo_page_url", sa.String(length=2048), nullable=True),
        sa.Column("photo_author", sa.String(length=500), nullable=True),
        sa.Column("photo_license", sa.String(length=200), nullable=True),
        sa.Column("photo_license_url", sa.String(length=2048), nullable=True),
        sa.Column("photo_illustrative", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("photo_attempts", sa.Integer(), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_photo_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("telegram_message_id", sa.String(length=100), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_items_canonical_url", "news_items", ["canonical_url"], unique=True)
    op.create_index("ix_news_items_created_at", "news_items", ["created_at"], unique=False)
    op.create_index("ix_news_items_status", "news_items", ["status"], unique=False)
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"], unique=False)
    op.create_index("ix_news_items_status_created_at", "news_items", ["status", "created_at"], unique=False)
    op.create_index("ix_news_items_status_published_at", "news_items", ["status", "published_at"], unique=False)

    op.create_table(
        "daily_api_usage",
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=14, scale=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("usage_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_api_usage")
    op.drop_index("ix_news_items_status_published_at", table_name="news_items")
    op.drop_index("ix_news_items_status_created_at", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_status", table_name="news_items")
    op.drop_index("ix_news_items_created_at", table_name="news_items")
    op.drop_index("ix_news_items_canonical_url", table_name="news_items")
    op.drop_table("news_items")
