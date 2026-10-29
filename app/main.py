"""Long-running polling worker; no inbound HTTP server or open port is required."""
from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import Settings
from app.db import create_database, initialize_database
from app.pipeline import run_cycle


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    settings.validate_runtime()
    try:
        ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown APP_TIMEZONE: {settings.app_timezone}") from exc
    if settings.publish_window_start_hour >= settings.publish_window_end_hour:
        raise RuntimeError("PUBLISH_WINDOW_START_HOUR must be earlier than PUBLISH_WINDOW_END_HOUR")

    engine, sessions = create_database(settings)
    try:
        await initialize_database(engine)
        logger.info(
            "Football News Bot started; feeds=%d, max_posts_per_day=%d, timezone=%s",
            len(settings.rss_feeds), settings.max_posts_per_day, settings.app_timezone,
        )
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            while True:
                try:
                    await run_cycle(sessions, client, settings)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A single bad feed/API response must not stop the worker permanently.
                    logger.exception("Unexpected pipeline cycle error")
                await asyncio.sleep(settings.poll_interval_minutes * 60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
