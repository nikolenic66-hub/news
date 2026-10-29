"""Telegram Bot API publishing with source and photographer attribution."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.models import NewsItem
from app.text import build_caption

logger = logging.getLogger(__name__)


class TelegramAPIError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class DeliveryUncertain(RuntimeError):
    """A timeout after a send request may mean Telegram accepted the post.

    These cases must not be blindly retried because that could publish a duplicate.
    """


@dataclass(frozen=True, slots=True)
class TelegramPostResult:
    message_id: int


async def download_photo(client: httpx.AsyncClient, item: NewsItem, max_bytes: int) -> tuple[bytes, str]:
    if not item.photo_url:
        raise ValueError("Queued item has no image URL")
    parsed = urlsplit(item.photo_url)
    if parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
        raise ValueError("Photo URL is outside the approved Wikimedia upload host")

    chunks: list[bytes] = []
    total = 0
    async with client.stream(
        "GET",
        item.photo_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        if urlsplit(str(response.url)).hostname != "upload.wikimedia.org":
            raise ValueError("Photo response host is not approved")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported image content type: {content_type or 'unknown'}")
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise ValueError("Image exceeds configured size limit")
            except ValueError as exc:
                if str(exc) == "Image exceeds configured size limit":
                    raise
                # Ignore malformed Content-Length and enforce the streaming limit instead.
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Image exceeds configured size limit")
            chunks.append(chunk)

    data = b"".join(chunks)
    valid_signature = (
        (content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (content_type == "image/webp" and len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )
    if not data or not valid_signature:
        raise ValueError("Downloaded file is empty or its signature does not match the image content type")
    return data, content_type

async def publish_photo(client: httpx.AsyncClient, settings: Settings, item: NewsItem,
                        image_bytes: bytes, content_type: str) -> TelegramPostResult:
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
    caption = build_caption(
        title=item.generated_title or item.source_title,
        body=item.generated_body or "",
        source_name=item.source_name,
        source_url=item.canonical_url,
        photo_author=item.photo_author or "Автор не указан",
        photo_license=item.photo_license or "Лицензия указана на странице файла",
        photo_license_url=item.photo_license_url or item.photo_page_url or item.photo_url or "",
        photo_page_url=item.photo_page_url or item.photo_url or "",
        illustrative=bool(item.photo_illustrative),
    )
    endpoint = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto"
    try:
        response = await client.post(
            endpoint,
            data={
                "chat_id": settings.telegram_channel_id,
                "caption": caption,
                "parse_mode": "HTML",
                "disable_notification": "true",
            },
            files={"photo": (f"football-news.{ext}", image_bytes, content_type)},
            timeout=httpx.Timeout(45.0, connect=10.0),
        )
    except httpx.RequestError as exc:
        # The request may have reached Telegram even if the response was lost.
        raise DeliveryUncertain(f"Telegram send request outcome unknown ({exc.__class__.__name__})") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise DeliveryUncertain("Telegram returned a non-JSON response after send") from exc

    if not payload.get("ok"):
        description = str(payload.get("description", "Telegram API rejected the post"))[:300]
        error_code = int(payload.get("error_code", response.status_code or 0))
        parameters = payload.get("parameters") or {}
        retryable = error_code == 429 or error_code >= 500
        if retryable and parameters.get("retry_after"):
            logger.warning("Telegram rate limit; retry_after=%s seconds", parameters["retry_after"])
        raise TelegramAPIError(description, retryable=retryable)

    message = payload.get("result") or {}
    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        raise DeliveryUncertain("Telegram accepted the call but returned no message id")
    return TelegramPostResult(message_id=message_id)
