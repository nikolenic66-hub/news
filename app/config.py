"""Environment-based configuration. Secrets are never stored in source code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FEEDS = (
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://feeds.theguardian.com/theguardian/football",
)


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    telegram_bot_token: str
    telegram_channel_id: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    rss_feeds: tuple[str, ...]
    app_timezone: str
    poll_interval_minutes: int
    max_posts_per_day: int
    publish_interval_minutes: int
    publish_window_start_hour: int
    publish_window_end_hour: int
    max_news_age_hours: int
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
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            rss_feeds=feeds,
            app_timezone=os.getenv("APP_TIMEZONE", "Europe/Moscow").strip(),
            poll_interval_minutes=_int_env("POLL_INTERVAL_MINUTES", 15, 1, 180),
            max_posts_per_day=_int_env("MAX_POSTS_PER_DAY", 10, 1, 10),
            publish_interval_minutes=_int_env("PUBLISH_INTERVAL_MINUTES", 90, 5, 1440),
            publish_window_start_hour=_int_env("PUBLISH_WINDOW_START_HOUR", 8, 0, 23),
            publish_window_end_hour=_int_env("PUBLISH_WINDOW_END_HOUR", 23, 1, 24),
            max_news_age_hours=_int_env("MAX_NEWS_AGE_HOURS", 36, 1, 168),
            max_items_to_process_per_cycle=_int_env("MAX_ITEMS_TO_PROCESS_PER_CYCLE", 5, 1, 25),
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
        missing = [
            name for name, value in (
                ("DATABASE_URL", self.database_url),
                ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
                ("TELEGRAM_CHANNEL_ID", self.telegram_channel_id),
                ("DEEPSEEK_API_KEY", self.deepseek_api_key),
            ) if not value
        ]
        if missing:
            raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
        if not self.rss_feeds:
            raise RuntimeError("RSS_FEEDS must contain at least one feed URL")
        if urlsplit(self.deepseek_base_url).scheme != "https":
            raise RuntimeError("DEEPSEEK_BASE_URL must use HTTPS")
