"""Minimal private-chat interface: /start and /news return current football RSS headlines."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape

import httpx

from app.config import Settings
from app.sources import fetch_all_feeds

logger = logging.getLogger(__name__)


def _format_news(items) -> str:
    if not items:
        return "Пока не удалось получить свежие новости. Попробуй ещё раз через несколько минут командой /news."
    blocks = ["⚽ <b>Свежие футбольные новости</b>"]
    for item in items[:3]:
        title = escape(item.title[:220])
        summary = escape((item.summary or "").strip()[:450])
        source = escape(item.source_name[:100])
        block = f"\n\n<b>{title}</b>"
        if summary:
            block += f"\n{summary}"
        block += f"\n<a href=\"{escape(item.url, quote=True)}\">Читать источник</a> · {source}"
        blocks.append(block)
    return "".join(blocks)[:3900]


async def _send_message(client: httpx.AsyncClient, token: str, chat_id: int, text: str) -> None:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=httpx.Timeout(25.0, connect=10.0),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected sendMessage")


async def run_private_bot(client: httpx.AsyncClient, settings: Settings) -> None:
    """Long-poll Telegram updates without requiring a channel ID or posting permissions."""
    if not settings.telegram_bot_token:
        logger.warning("Private Telegram bot disabled: TELEGRAM_BOT_TOKEN is not configured")
        return

    token = settings.telegram_bot_token
    url = f"https://api.telegram.org/bot{token}"
    offset = 0
    logger.info("Telegram private chat handler started; /start and /news are enabled")
    while True:
        try:
            response = await client.get(
                f"{url}/getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": '["message"]'},
                timeout=httpx.Timeout(35.0, connect=10.0),
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError("Telegram getUpdates returned ok=false")
            for update in payload.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                text = (message.get("text") or "").strip().lower()
                if not isinstance(chat_id, int) or not text.startswith("/"):
                    continue
                command = text.split()[0].split("@", 1)[0]
                if command not in {"/start", "/news", "/latest"}:
                    continue
                if command == "/start":
                    greeting = "Привет! Я футбольный новостной бот. Вот свежие новости. В любой момент напиши /news, чтобы получить новые."
                else:
                    greeting = ""
                items = await fetch_all_feeds(client, settings.rss_feeds)
                # RSS entries are already newest-first for the configured sources; sort defensively.
                items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                news = _format_news(items)
                reply = f"{escape(greeting)}\n\n{news}" if greeting else news
                await _send_message(client, token, chat_id, reply)
                logger.info("Replied to Telegram private command %s", command)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Avoid logging token-bearing URLs or raw Telegram response bodies.
            logger.warning("Telegram private bot polling failed (%s); retrying in 5 seconds", exc.__class__.__name__)
            await asyncio.sleep(5)
