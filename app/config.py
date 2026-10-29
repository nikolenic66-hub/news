"""Environment-based configuration with safe defaults and spend limits."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FEEDS = (
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.theguardian.com/football/rss",
)
APP_MODES = {"collect_only", "prepare", "live"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    return max(minimum, min(maximum, value))


def _decimal_env(name: str, default: str, minimum: str = "0") -> Decimal:
    raw = os.getenv(name, default).strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number") from exc
    if not value.is_finite() or value < Decimal(minimum):
        raise ValueError(f"{name} must be a finite number >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    app_mode: str
    telegram_bot_token: str
    telegram_channel_id: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_daily_budget_usd: Decimal
    deepseek_input_price_per_million_usd: Decimal
    deepseek_output_price_per_million_usd: Decimal
    max_deepseek_calls_per_day: int
    deepseek_max_output_tokens: int
    rss_feeds: tuple[str, ...]
    app_timezone: str
    poll_interval_minutes: int
    max_posts_per_day: int
    publish_interval_minutes: int
    publish_window_start_hour: int
    publish_window_end_hour: int
    max_news_age_hours: int
    db_retention_days: int
    max_items_to_process_per_cycle: int
    wikimedia_user_agent: str
    max_photo_attempts: int
    photo_retry_hours: int
    max_photo_bytes: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        raw_feeds = os.getenv("RSS_FEEDS", ",".join(DEFAULT_FEEDS))
        feeds = tuple(dict.fromkeys(url.strip() for url in raw_feeds.replace("\n", ",").split(",") if url.strip()))
        return cls(
            database_url=os.getenv("DATABASE_URL", "").strip(),
            app_mode=os.getenv("APP_MODE", "collect_only").strip().lower(),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            # These are conservative peak prices from the official pricing page as at 2026-10-29.
            deepseek_daily_budget_usd=_decimal_env("DEEPSEEK_DAILY_BUDGET_USD", "0.08"),
            deepseek_input_price_per_million_usd=_decimal_env("DEEPSEEK_INPUT_PRICE_PER_MILLION_USD", "0.30"),
            deepseek_output_price_per_million_usd=_decimal_env("DEEPSEEK_OUTPUT_PRICE_PER_MILLION_USD", "1.20"),
            max_deepseek_calls_per_day=_int_env("MAX_DEEPSEEK_CALLS_PER_DAY", 30, 1, 100),
            deepseek_max_output_tokens=_int_env("DEEPSEEK_MAX_OUTPUT_TOKENS", 700, 200, 1200),
            rss_feeds=feeds,
            app_timezone=os.getenv("APP_TIMEZONE", "Europe/Moscow").strip(),
            poll_interval_minutes=_int_env("POLL_INTERVAL_MINUTES", 15, 5, 180),
            max_posts_per_day=_int_env("MAX_POSTS_PER_DAY", 10, 1, 10),
            publish_interval_minutes=_int_env("PUBLISH_INTERVAL_MINUTES", 90, 5, 1440),
            publish_window_start_hour=_int_env("PUBLISH_WINDOW_START_HOUR", 8, 0, 23),
            publish_window_end_hour=_int_env("PUBLISH_WINDOW_END_HOUR", 23, 1, 24),
            max_news_age_hours=_int_env("MAX_NEWS_AGE_HOURS", 36, 1, 168),
            db_retention_days=_int_env("DB_RETENTION_DAYS", 120, 30, 730),
            max_items_to_process_per_cycle=_int_env("MAX_ITEMS_TO_PROCESS_PER_CYCLE", 3, 1, 10),
            wikimedia_user_agent=os.getenv(
                "WIKIMEDIA_USER_AGENT",
                "FootballNewsBot/0.1 (contact: configure-admin-email)",
            ).strip(),
            max_photo_attempts=_int_env("MAX_PHOTO_ATTEMPTS", 4, 1, 10),
            photo_retry_hours=_int_env("PHOTO_RETRY_HOURS", 6, 1, 72),
            max_photo_bytes=_int_env("MAX_PHOTO_BYTES", 9_000_000, 100_000, 10_000_000),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )

    def validate_runtime(self) -> None:
        if self.app_mode not in APP_MODES:
            raise RuntimeError("APP_MODE must be one of: collect_only, prepare, live")

        missing = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if self.app_mode in {"prepare", "live"} and not self.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if self.app_mode == "live":
            if not self.telegram_bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self.telegram_channel_id:
                missing.append("TELEGRAM_CHANNEL_ID")
        if missing:
            raise RuntimeError("Missing required environment variables for APP_MODE=" + self.app_mode + ": " + ", ".join(missing))
        if self.database_url and urlsplit(self.database_url).scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL")
        if not self.rss_feeds:
            raise RuntimeError("RSS_FEEDS must contain at least one feed URL")
        if self.app_mode in {"prepare", "live"} and urlsplit(self.deepseek_base_url).scheme != "https":
            raise RuntimeError("DEEPSEEK_BASE_URL must use HTTPS")
        if self.app_mode in {"prepare", "live"} and ("example.com" in self.wikimedia_user_agent or "configure-admin-email" in self.wikimedia_user_agent):
            raise RuntimeError("Set WIKIMEDIA_USER_AGENT to a descriptive value with a real contact before enabling photo search")
        if self.deepseek_daily_budget_usd <= 0:
            raise RuntimeError("DEEPSEEK_DAILY_BUDGET_USD must be > 0")
        if self.deepseek_input_price_per_million_usd < 0 or self.deepseek_output_price_per_million_usd < 0:
            raise RuntimeError("DeepSeek price settings cannot be negative")
