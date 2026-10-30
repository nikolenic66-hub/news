"""Private-chat football news: rank important stories and rewrite them in Russian with DeepSeek."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.editor import create_draft
from app.models import NewsItem
from app.sources import FeedItem, fetch_all_feeds

logger = logging.getLogger(__name__)

_FOOTBALL_MARKERS = (
    "футбол", "футболь", "рпл", "апл", "ла лига", "серия а", "бундеслиг",
    "лига чемпионов", "лига европы", "лига конференций", "кубок россии",
    "кубок англии", "чемпионат мира", "чемпионат европы", "сборная россии",
    "премьер-лиг", "первой лиги", "первая лига", "суперкубок",
    "манчестер", "ливерпуль", "арсенал", "челси", "реал мадрид", "барселона",
    "бавария", "псж", "интер", "милан", "ювентус", "атлетико", "тоттенхэм",
    "мбаппе", "месси", "роналду", "холанд", "салах", "неймар", "винiciус",
    "football", "champions league", "premier league", "la liga", "serie a",
    "bundesliga", "europa league", "world cup", "euros",
)

_IMPORTANCE_TERMS = {
    "transfer": 5, "signs": 4, "signed": 4, "sack": 4, "sacked": 4,
    "resigns": 4, "injury": 3, "injured": 3, "champions league": 5,
    "premier league": 3, "world cup": 4, "final": 3, "semi-final": 3,
    "qualify": 3, "qualifies": 3, "title race": 3, "record": 2,
    "mbappe": 3, "messi": 3, "ronaldo": 3, "haaland": 3, "salah": 3,
    "vinicius": 3, "bellingham": 3, "arsenal": 2, "liverpool": 2,
    "manchester city": 2, "manchester united": 2, "chelsea": 2,
    "real madrid": 2, "barcelona": 2, "bayern": 2, "psg": 2,
    "newcastle": 2, "everton": 1,
}


def _rank(item: FeedItem, now: datetime) -> float:
    title = item.title.casefold()
    summary = (item.summary or "").casefold()
    text = f"{title} {summary[:500]}"
    score = 0.0
    for term, weight in _IMPORTANCE_TERMS.items():
        if term in title:
            score += weight
        elif term in text:
            score += weight * 0.35
    published = item.published_at
    if published:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - published.astimezone(timezone.utc)).total_seconds() / 3600)
        score += max(0.0, 5.0 - age_hours / 6.0)
    if len(item.summary or "") > 180:
        score += 0.5
    return score


def _format_news(drafts: list[tuple[str, str]]) -> str:
    if not drafts:
        return "Пока не получилось подготовить достоверные новости. Попробуй ещё раз чуть позже командой /news."
    blocks = ["⚽ <b>Главное в футболе</b>"]
    for title, body in drafts:
        blocks.append(f"\n\n<b>{escape(title)}</b>\n{escape(body)}")
    return "\n".join(blocks)[:3900]


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


async def _prepare_top_news(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker,
    settings: Settings,
) -> list[tuple[str, str]]:
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    items = await fetch_all_feeds(client, settings.rss_feeds)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=settings.max_news_age_hours)
    fresh = []
    for item in items:
        # Some supplementary feeds cover several sports. Keep only clearly
        # football-related entries so hockey, tennis and other noise never
        # reaches the editorial model.
        searchable = f"{item.title} {item.summary[:1200]}".casefold()
        if not any(marker in searchable for marker in _FOOTBALL_MARKERS):
            continue
        published = item.published_at
        if not published:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if cutoff <= published.astimezone(timezone.utc) <= now + timedelta(hours=1):
            fresh.append(item)
    fresh.sort(key=lambda item: _rank(item, now), reverse=True)

    prepared: list[tuple[str, str]] = []
    # Limit API spend per command. The editorial layer rejects weak or unclear stories.
    for source in fresh[:5]:
        draft_item = NewsItem(
            canonical_url=source.url,
            source_name=source.source_name,
            source_title=source.title,
            source_summary=source.summary,
            published_at_source=source.published_at,
        )
        try:
            draft = await create_draft(client, sessions, settings, draft_item)
        except Exception as exc:
            logger.warning("Editorial API failed while preparing /news (%s)", exc.__class__.__name__)
            if not prepared:
                raise
            break
        if draft.publish:
            prepared.append((draft.title, draft.body))
        if len(prepared) >= 3:
            break
    return prepared


async def run_private_bot(
    client: httpx.AsyncClient,
    settings: Settings,
    sessions: async_sessionmaker,
) -> None:
    """Long-poll Telegram updates without requiring a channel ID or posting permissions."""
    if not settings.telegram_bot_token:
        logger.warning("Private Telegram bot disabled: TELEGRAM_BOT_TOKEN is not configured")
        return

    token = settings.telegram_bot_token
    url = f"https://api.telegram.org/bot{token}"
    offset = 0
    logger.info(
        "Telegram private chat handler started; /start and /news are enabled; deepseek_key_configured=%s",
        bool(settings.deepseek_api_key),
    )
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
                incoming = (message.get("text") or "").strip().lower()
                if not isinstance(chat_id, int) or not incoming.startswith("/"):
                    continue
                command = incoming.split()[0].split("@", 1)[0]
                if command not in {"/start", "/news", "/latest"}:
                    continue
                if command == "/start":
                    await _send_message(
                        client, token, chat_id,
                        "Привет! Я футбольный новостной бот. Напиши /news, и я выберу главные свежие события и подготовлю короткие новости на русском языке.",
                    )
                    continue
                await _send_message(client, token, chat_id, "🔎 Отбираю главные новости и готовлю русскоязычные материалы. Это займёт несколько секунд.")
                try:
                    drafts = await _prepare_top_news(client, sessions, settings)
                    await _send_message(client, token, chat_id, _format_news(drafts))
                    logger.info("Prepared %d Russian football news stories for /news", len(drafts))
                except Exception as exc:
                    logger.warning("Could not prepare /news response (%s)", exc.__class__.__name__)
                    await _send_message(
                        client, token, chat_id,
                        "Не удалось подготовить новости через редактор ИИ. Проверь настройки DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL и DEEPSEEK_MODEL, затем попробуй /news ещё раз.",
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram private bot polling failed (%s); retrying in 5 seconds", exc.__class__.__name__)
            await asyncio.sleep(5)
