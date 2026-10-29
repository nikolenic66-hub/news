"""Orchestrate RSS ingestion, DeepSeek editing, licensed photos and Telegram publishing."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.editor import create_draft
from app.models import NewsItem
from app.photos import find_licensed_photo
from app.sources import FeedItem, fetch_all_feeds
from app.telegram import DeliveryUncertain, TelegramAPIError, download_photo, publish_photo

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normal_title(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    return " ".join(re.findall(r"[a-zа-я0-9]+", value, flags=re.IGNORECASE))


def _titles_are_similar(left: str, right: str) -> bool:
    left_norm, right_norm = _normal_title(left), _normal_title(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.90:
        return True
    left_words, right_words = set(left_norm.split()), set(right_norm.split())
    common = left_words & right_words
    union = left_words | right_words
    return len(common) >= 4 and bool(union) and len(common) / len(union) >= 0.82


def _timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def expire_stale_candidates(session: AsyncSession, settings: Settings) -> int:
    cutoff = _now_utc() - timedelta(hours=settings.max_news_age_hours)
    result = await session.execute(
        select(NewsItem).where(
            NewsItem.status.in_({"new", "processing", "awaiting_photo", "queued"}),
            or_(NewsItem.published_at_source.is_(None), NewsItem.published_at_source < cutoff),
        )
    )
    items = list(result.scalars().all())
    for item in items:
        item.status = "rejected"
        item.last_error = "News source is missing a date or became stale before publication"
    if items:
        await session.commit()
        logger.info("Expired %d stale news candidates", len(items))
    return len(items)


async def collect_news(session: AsyncSession, client: httpx.AsyncClient, settings: Settings) -> int:
    entries = await fetch_all_feeds(client, settings.rss_feeds)
    if not entries:
        return 0

    now = _now_utc()
    freshness_cutoff = now - timedelta(hours=settings.max_news_age_hours)
    incoming_urls = [item.url for item in entries]
    known_result = await session.execute(
        select(NewsItem.canonical_url).where(NewsItem.canonical_url.in_(incoming_urls))
    )
    known_urls = set(known_result.scalars().all())
    recent_result = await session.execute(
        select(NewsItem.source_title).where(NewsItem.created_at >= now - timedelta(days=10)).limit(1000)
    )
    recent_titles = list(recent_result.scalars().all())
    added = 0

    for feed_item in entries:
        if feed_item.url in known_urls:
            continue
        published = _timestamp(feed_item.published_at)
        # If a feed has no timestamp, we cannot establish that the item is fresh enough to publish.
        if published is None:
            logger.debug("Skipping undated RSS item from %s", feed_item.source_name)
            continue
        if published < freshness_cutoff or published > now + timedelta(hours=6):
            continue
        # One event copied across several feeds should enter the queue only once.
        if any(_titles_are_similar(feed_item.title, old_title) for old_title in recent_titles):
            continue
        session.add(NewsItem(
            canonical_url=feed_item.url,
            source_name=feed_item.source_name[:250],
            source_title=feed_item.title[:1000],
            source_summary=feed_item.summary[:5000],
            published_at_source=published,
            status="new",
            attempts=0,
            photo_attempts=0,
            publish_attempts=0,
            photo_illustrative=1,
        ))
        known_urls.add(feed_item.url)
        recent_titles.append(feed_item.title)
        added += 1

    if added:
        await session.commit()
        logger.info("New football news candidates stored: %d", added)
    else:
        await session.rollback()
    return added


async def process_new_items(session: AsyncSession, client: httpx.AsyncClient, settings: Settings) -> int:
    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.status == "new", NewsItem.attempts < 3)
        .order_by(NewsItem.created_at.asc())
        .limit(settings.max_items_to_process_per_cycle)
    )
    items = list(result.scalars().all())
    completed = 0
    for item in items:
        item.status = "processing"
        item.attempts = (item.attempts or 0) + 1
        item.last_attempt_at = _now_utc()
        item.last_error = None
        await session.commit()
        try:
            draft = await create_draft(client, settings, item)
        except Exception as exc:
            item.last_error = f"Editorial API error: {exc.__class__.__name__}"
            item.status = "new" if item.attempts < 3 else "failed"
            await session.commit()
            logger.warning("Editorial processing failed for item id=%s (%s)", item.id, exc.__class__.__name__)
            continue

        if not draft.publish:
            item.status = "rejected"
            item.last_error = (draft.reason or "rejected by editorial gate")[:500]
            await session.commit()
            logger.info("Candidate rejected by editorial gate, id=%s, reason=%s", item.id, item.last_error)
            completed += 1
            continue

        item.generated_title = draft.title
        item.generated_body = draft.body
        item.category = draft.category
        item.photo_query = draft.photo_query
        item.status = "awaiting_photo"
        item.last_error = None
        await session.commit()
        completed += 1
    return completed


async def attach_licensed_photos(session: AsyncSession, client: httpx.AsyncClient, settings: Settings) -> int:
    retry_cutoff = _now_utc() - timedelta(hours=settings.photo_retry_hours)
    result = await session.execute(
        select(NewsItem)
        .where(
            NewsItem.status == "awaiting_photo",
            NewsItem.photo_attempts < settings.max_photo_attempts,
            or_(NewsItem.last_photo_attempt_at.is_(None), NewsItem.last_photo_attempt_at <= retry_cutoff),
        )
        .order_by(NewsItem.created_at.asc())
        .limit(settings.max_items_to_process_per_cycle)
    )
    items = list(result.scalars().all())
    attached = 0
    for item in items:
        item.photo_attempts = (item.photo_attempts or 0) + 1
        item.last_photo_attempt_at = _now_utc()
        await session.commit()
        try:
            photo = await find_licensed_photo(client, settings, item.photo_query or item.generated_title or item.source_title)
        except Exception as exc:
            photo = None
            item.last_error = f"Photo search error: {exc.__class__.__name__}"

        if not photo:
            item.last_error = item.last_error or "No suitable Wikimedia Commons photo with accepted license yet"
            if item.photo_attempts >= settings.max_photo_attempts:
                item.status = "needs_review"
                item.last_error += "; automatic publication skipped"
            await session.commit()
            logger.info("No licensed photo for item id=%s (attempt %s)", item.id, item.photo_attempts)
            continue

        item.photo_url = photo.image_url
        item.photo_page_url = photo.page_url
        item.photo_author = photo.author
        item.photo_license = photo.license_name
        item.photo_license_url = photo.license_url
        item.photo_illustrative = int(photo.illustrative)
        item.status = "queued"
        item.last_error = None
        await session.commit()
        logger.info("Article queued, id=%s, illustrative_photo=%s", item.id, bool(item.photo_illustrative))
        attached += 1
    return attached


async def _daily_published_count(session: AsyncSession, local_now: datetime, timezone_name: str) -> int:
    tz = ZoneInfo(timezone_name)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(timezone.utc)
    end_utc = local_end.astimezone(timezone.utc)
    result = await session.execute(
        select(func.count(NewsItem.id)).where(
            NewsItem.status == "published", NewsItem.published_at >= start_utc, NewsItem.published_at < end_utc
        )
    )
    return int(result.scalar_one() or 0)


async def publish_one_due(session: AsyncSession, client: httpx.AsyncClient,
                          settings: Settings) -> bool:
    tz = ZoneInfo(settings.app_timezone)
    now = _now_utc()
    local_now = now.astimezone(tz)
    if local_now.hour < settings.publish_window_start_hour or local_now.hour >= settings.publish_window_end_hour:
        return False

    unresolved = await session.scalar(select(func.count(NewsItem.id)).where(NewsItem.status == "uncertain"))
    if int(unresolved or 0) > 0:
        logger.error("Publishing paused: a previous Telegram send has uncertain delivery; inspect the channel before retrying")
        return False

    count = await _daily_published_count(session, local_now, settings.app_timezone)
    if count >= settings.max_posts_per_day:
        return False

    last_result = await session.execute(
        select(func.max(NewsItem.published_at)).where(NewsItem.status == "published")
    )
    last_published = _timestamp(last_result.scalar_one_or_none())
    if last_published and now < last_published + timedelta(minutes=settings.publish_interval_minutes):
        return False

    result = await session.execute(
        select(NewsItem).where(NewsItem.status == "queued")
        .order_by(NewsItem.created_at.asc()).limit(1)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return False

    # Commit the publishing state before contacting Telegram. An interrupted send is
    # marked uncertain rather than blindly retried, avoiding duplicate channel posts.
    item.status = "publishing"
    item.publish_attempts = (item.publish_attempts or 0) + 1
    item.last_error = None
    await session.commit()

    try:
        image_bytes, content_type = await download_photo(client, item, settings.max_photo_bytes)
    except Exception as exc:
        item.status = "queued" if item.publish_attempts < 5 else "failed"
        item.last_error = f"Photo download failed: {exc.__class__.__name__}"
        await session.commit()
        logger.warning("Could not download image for item id=%s (%s)", item.id, exc.__class__.__name__)
        return False

    try:
        response = await publish_photo(client, settings, item, image_bytes, content_type)
    except DeliveryUncertain as exc:
        item.status = "uncertain"
        item.last_error = str(exc)[:500]
        await session.commit()
        logger.error("Telegram delivery uncertain for item id=%s; not retrying automatically", item.id)
        return False
    except TelegramAPIError as exc:
        item.status = "queued" if exc.retryable and item.publish_attempts < 5 else "failed"
        item.last_error = f"Telegram rejected the post: {str(exc)[:300]}"
        await session.commit()
        logger.warning("Telegram did not accept item id=%s (retryable=%s)", item.id, exc.retryable)
        return False
    except Exception as exc:
        # Unknown failure after the send path begins is treated conservatively.
        item.status = "uncertain"
        item.last_error = f"Unexpected send failure: {exc.__class__.__name__}"
        await session.commit()
        logger.exception("Uncertain Telegram delivery for item id=%s", item.id)
        return False

    item.status = "published"
    item.published_at = _now_utc()
    item.telegram_message_id = str(response.message_id)
    item.last_error = None
    await session.commit()
    logger.info("Published football news id=%s to channel (daily count will update)", item.id)
    return True


async def recover_stale_processing(session: AsyncSession) -> int:
    cutoff = _now_utc() - timedelta(minutes=20)
    result = await session.execute(
        select(NewsItem).where(NewsItem.status == "processing", NewsItem.updated_at < cutoff)
    )
    items = list(result.scalars().all())
    for item in items:
        item.status = "new" if item.attempts < 3 else "failed"
        item.last_error = "Recovered an interrupted editorial-processing attempt"
    if items:
        await session.commit()
        logger.warning("Recovered %d interrupted editorial attempts", len(items))
    return len(items)


async def recover_stale_sends(session: AsyncSession) -> int:
    cutoff = _now_utc() - timedelta(minutes=15)
    result = await session.execute(
        select(NewsItem).where(NewsItem.status == "publishing", NewsItem.updated_at < cutoff)
    )
    items = list(result.scalars().all())
    for item in items:
        item.status = "uncertain"
        item.last_error = "Application restarted while Telegram delivery was in progress; check the channel before retrying"
    if items:
        await session.commit()
        logger.error("Marked %d interrupted publishing attempts as uncertain to prevent duplicates", len(items))
    return len(items)


async def run_cycle(sessions: async_sessionmaker, client: httpx.AsyncClient, settings: Settings) -> None:
    async with sessions() as session:
        await recover_stale_processing(session)
        await recover_stale_sends(session)
        await expire_stale_candidates(session, settings)
        await collect_news(session, client, settings)
        await process_new_items(session, client, settings)
        await attach_licensed_photos(session, client, settings)
        await publish_one_due(session, client, settings)
