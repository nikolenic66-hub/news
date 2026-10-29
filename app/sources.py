"""RSS collection. Feed content is treated as untrusted source data, never as instructions."""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass(frozen=True, slots=True)
class FeedItem:
    url: str
    source_name: str
    title: str
    summary: str
    published_at: datetime | None


def html_to_text(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", unescape(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower = key.lower()
        if lower.startswith("utm_") or lower in TRACKING_KEYS:
            continue
        query.append((key, value))
    clean_path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), clean_path, urlencode(query, doseq=True), ""))


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def _entry_summary(entry) -> str:
    values: list[str] = []
    for part in entry.get("content", []) or []:
        if isinstance(part, dict) and part.get("value"):
            values.append(html_to_text(str(part["value"])))
    if entry.get("summary"):
        values.append(html_to_text(str(entry.get("summary", ""))))
    if entry.get("description"):
        values.append(html_to_text(str(entry.get("description", ""))))
    # Preserve the richest snippet, without copying an entire page or repeated boilerplate.
    values = list(dict.fromkeys(v for v in values if v))
    return max(values, key=len, default="")[:5000]


async def fetch_feed(client: httpx.AsyncClient, feed_url: str) -> list[FeedItem]:
    try:
        response = await client.get(feed_url, headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("RSS feed unavailable (%s): %s", urlsplit(feed_url).netloc, exc.__class__.__name__)
        return []

    feed_name = html_to_text(str(parsed.feed.get("title", ""))) or urlsplit(feed_url).netloc
    results: list[FeedItem] = []
    for entry in parsed.entries:
        title = html_to_text(str(entry.get("title", "")))
        url = canonicalize_url(str(entry.get("link", "")))
        if not title or not url:
            continue
        results.append(FeedItem(
            url=url,
            source_name=feed_name[:250],
            title=title[:1000],
            summary=_entry_summary(entry),
            published_at=_entry_datetime(entry),
        ))
    logger.info("RSS feed checked: %s, items=%d", urlsplit(feed_url).netloc, len(results))
    return results


async def fetch_all_feeds(client: httpx.AsyncClient, feed_urls: tuple[str, ...]) -> list[FeedItem]:
    import asyncio

    batches = await asyncio.gather(*(fetch_feed(client, url) for url in feed_urls), return_exceptions=True)
    combined: list[FeedItem] = []
    seen: set[str] = set()
    for batch in batches:
        if isinstance(batch, Exception):
            logger.warning("RSS collection failed: %s", batch.__class__.__name__)
            continue
        for item in batch:
            if item.url not in seen:
                seen.add(item.url)
                combined.append(item)
    return combined
