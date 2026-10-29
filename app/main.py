"""Worker entry point. Supports a one-shot mode for scheduled executions."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import text

from app.config import Settings
from app.db import create_database
from app.pipeline import run_cycle
from app.sources import fetch_all_feeds
from app.telegram_bot import run_private_bot

# Session-level PostgreSQL advisory lock prevents overlapping runs from posting duplicates.
_PIPELINE_LOCK_ID = 726100103


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def apply_migrations(settings: Settings) -> None:
    """Run versioned schema migrations before touching pipeline tables."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("Database migration timed out after 60 seconds") from exc
    if process.returncode != 0:
        text_output = output.decode("utf-8", errors="replace")
        # Never echo a raw secret-bearing connection string to logs.
        if settings.database_url:
            text_output = text_output.replace(settings.database_url, "[DATABASE_URL REDACTED]")
        logging.getLogger(__name__).error("Database migration failed:\n%s", text_output[-2500:])
        raise RuntimeError("Database migration failed; see the redacted application logs")


async def run_locked_cycle(engine, sessions, client: httpx.AsyncClient, settings: Settings) -> bool:
    """Run one cycle only if no overlapping worker currently holds the database lock."""
    async with engine.connect() as lock_connection:
        result = await lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": _PIPELINE_LOCK_ID},
        )
        acquired = bool(result.scalar_one())
        await lock_connection.commit()
        if not acquired:
            logging.getLogger(__name__).warning("Another worker run is active; skipping this cycle")
            return False
        try:
            await run_cycle(sessions, client, settings)
            return True
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": _PIPELINE_LOCK_ID},
            )
            await lock_connection.commit()


async def main(once: bool = False, check: bool = False) -> None:
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

    await apply_migrations(settings)
    engine, sessions = create_database(settings)
    try:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if check:
                # Read-only preflight after versioned migrations; never calls DeepSeek, photos, or Telegram.
                async with engine.connect() as connection:
                    database_result = await connection.execute(text("SELECT 1"))
                    if database_result.scalar_one() != 1:
                        raise RuntimeError("Database preflight returned an unexpected result")
                logger.info("Preflight OK: PostgreSQL connection and migrations are available")
                items = await fetch_all_feeds(client, settings.rss_feeds)
                if items:
                    logger.info("Preflight OK: RSS returned %d recent candidates across %d configured feeds", len(items), len(settings.rss_feeds))
                else:
                    logger.warning("Database is reachable, but all RSS feeds returned zero candidates. Check feed URLs/access before enabling prepare/live.")
                return
            logger.info(
                "Football News Bot started; mode=%s, feeds=%d, max_posts=%d/day, "
                "DeepSeek calls=%d/day, timezone=%s, once=%s, telegram_token_configured=%s",
                settings.app_mode,
                len(settings.rss_feeds),
                settings.max_posts_per_day,
                settings.max_deepseek_calls_per_day,
                settings.app_timezone,
                once,
                bool(settings.telegram_bot_token),
            )
            # Always start the task during continuous runs so missing token configuration
            # is reported explicitly by run_private_bot instead of silently disabling it.
            telegram_task = (
                asyncio.create_task(run_private_bot(client, settings), name="telegram-private-bot")
                if not check
                else None
            )
            try:
                while True:
                    try:
                        await run_locked_cycle(engine, sessions, client, settings)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # A scheduled one-shot run should report failure to the scheduler.
                        logger.exception("Unexpected pipeline cycle error")
                        if once:
                            raise
                    finally:
                        # Return idle connections so Neon can scale to zero between polling cycles.
                        await engine.dispose()
                    if once:
                        break
                    await asyncio.sleep(settings.poll_interval_minutes * 60)
            finally:
                if telegram_task is not None:
                    telegram_task.cancel()
                    await asyncio.gather(telegram_task, return_exceptions=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Football News Bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config, apply/check migrations, test DB and RSS without AI/photo/Telegram calls.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one pipeline cycle and exit (for Amvera Cron Jobs).",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(once=args.once, check=args.check))
    except KeyboardInterrupt:
        pass
