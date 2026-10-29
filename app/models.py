"""Database models for news, publication history, and daily API usage."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        Index("ix_news_items_status_created_at", "status", "created_at"),
        Index("ix_news_items_status_published_at", "status", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(250), default="Источник")
    source_title: Mapped[str] = mapped_column(Text)
    source_summary: Mapped[str] = mapped_column(Text, default="")
    published_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # new -> processing -> awaiting_photo -> queued -> publishing -> published
    # Other terminal states: rejected, failed, needs_review, uncertain.
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    generated_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    photo_query: Mapped[str | None] = mapped_column(String(300), nullable=True)

    photo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_page_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    photo_license_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_illustrative: Mapped[int] = mapped_column(Integer, default=1)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    photo_attempts: Mapped[int] = mapped_column(Integer, default=0)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_photo_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class DailyAPIUsage(Base):
    """One compact accounting row per local day; only stores aggregate usage, not prompts."""

    __tablename__ = "daily_api_usage"

    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
