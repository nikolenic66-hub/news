"""Private-chat football news: rank important stories and rewrite them in Russian with DeepSeek."""
from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.editor import create_draft
from app.models import NewsItem
from app.sources import FeedItem, fetch_all_feeds
from app.usage import DeepSeekBudgetExceeded

logger = logging.getLogger(__name__)

_FOOTBALL_MARKERS = (
    "футбол", "футболь", "рпл", "апл", "ла лига", "серия а", "бундеслиг",
    "лига чемпионов", "лига европы", "лига конференций", "кубок россии",
    "кубок англии", "чемпионат мира", "чемпионат европы", "сборная россии",
    "премьер-лиг", "первой лиги", "первая лига", "суперкубок",
    "манчестер", "ливерпуль", "арсенал", "челси", "реал мадрид", "барселона",
    "бавария", "псж", "интер", "милан", "ювентус", "атлетико", "тоттенхэм",
    "мбаппе", "месси", "роналду", "холанд", "салах", "неймар", "винисиус",
    "football", "champions league", "premier league", "la liga", "serie a",
    "bundesliga", "europa league", "world cup", "euros",
)

_WOMENS_FOOTBALL_MARKERS = (
    "женск", "женщин", "женская", "женской", "женский футбол",
    "women", "woman", "women's", "womens", "femení", "femeni",
    "femenino", "feminino", "liga f", "uwcl",
)
_WOMENS_BARCA_REAL_MARKERS = (
    "барселона", "барса", "barcelona", "barça", "real madrid",
    "реал мадрид", "реал",
)
_MATCH_MARKERS = (
    "матч", "встреч", "сыгра", "обыгра", "побед", "проигра",
    "ничь", "гол", "разгром", "match", "beat", "defeat", "draw",
    "win", "lost", "score",
)


def _is_allowed_football_item(item: FeedItem) -> bool:
    searchable = f"{item.title} {item.summary[:1200]}".casefold()
    if not any(marker in searchable for marker in _FOOTBALL_MARKERS):
        return False
    if any(marker in searchable for marker in _WOMENS_FOOTBALL_MARKERS):
        # Women's football is excluded completely, except match reports
        # involving Barcelona or Real Madrid, as explicitly requested.
        has_allowed_club = any(marker in searchable for marker in _WOMENS_BARCA_REAL_MARKERS)
        has_match_context = any(marker in searchable for marker in _MATCH_MARKERS)
        if not (has_allowed_club and has_match_context):
            return False
    return True


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


_DUPLICATE_STOPWORDS = {
    "а", "без", "был", "была", "были", "быть", "в", "во", "для", "до",
    "его", "ее", "её", "если", "за", "и", "из", "или", "к", "как",
    "команда", "клуб", "лига", "матч", "между", "на", "над", "не",
    "но", "о", "об", "от", "после", "по", "под", "при", "с", "со",
    "стал", "стала", "стали", "у", "футбол", "футбола", "футболу",
    "чемпионат", "это", "the", "a", "an", "and", "in", "of", "to",
    "football", "match", "club", "team",
}


def _duplicate_text(title: str, summary: str = "") -> tuple[str, set[str]]:
    raw = f"{title} {summary[:700]}".casefold().replace("ё", "е")
    tokens = set(re.findall(r"[a-zа-я0-9]+", raw))
    useful = {token for token in tokens if len(token) > 2 and token not in _DUPLICATE_STOPWORDS}
    compact_title = " ".join(
        token for token in re.findall(r"[a-zа-я0-9]+", title.casefold().replace("ё", "е"))
        if len(token) > 2 and token not in _DUPLICATE_STOPWORDS
    )
    return compact_title, useful


def _are_duplicate_stories(
    left_title: str, left_summary: str, right_title: str, right_summary: str
) -> bool:
    left_compact, left_tokens = _duplicate_text(left_title, left_summary)
    right_compact, right_tokens = _duplicate_text(right_title, right_summary)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    title_similarity = SequenceMatcher(None, left_compact, right_compact).ratio()
    return overlap >= 0.62 or title_similarity >= 0.78


def _deduplicate_feed_items(items: list[FeedItem], now: datetime) -> list[FeedItem]:
    """Keep the strongest representative of each story before spending DeepSeek calls."""
    ranked = sorted(items, key=lambda item: _rank(item, now), reverse=True)
    unique: list[FeedItem] = []
    for item in ranked:
        if any(
            _are_duplicate_stories(item.title, item.summary or "", kept.title, kept.summary or "")
            for kept in unique
        ):
            logger.info("Skipped duplicate RSS story before DeepSeek: %s", item.title[:120])
            continue
        unique.append(item)
    return unique


def _deduplicate_drafts(drafts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Second duplicate guard after editorial rewriting changes titles and wording."""
    unique: list[tuple[str, str]] = []
    for title, body in drafts:
        if any(
            _are_duplicate_stories(title, body, kept_title, kept_body)
            for kept_title, kept_body in unique
        ):
            logger.info("Skipped duplicate editorial draft after DeepSeek: %s", title[:120])
            continue
        unique.append((title, body))
    return unique


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


def _format_news_item(title: str, body: str) -> str:
    return f"<b>{escape(title)}</b>\\n\\n{escape(body)}"


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
        if not _is_allowed_football_item(item):
            continue
        published = item.published_at
        if not published:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if cutoff <= published.astimezone(timezone.utc) <= now + timedelta(hours=1):
            fresh.append(item)
    fresh = _deduplicate_feed_items(fresh, now)

    prepared: list[tuple[str, str]] = []
    # Limit API spend per command. Duplicates are removed before any paid editorial call.
    for source in fresh[:8]:
        draft_item = NewsItem(
            canonical_url=source.url,
            source_name=source.source_name,
            source_title=source.title,
            source_summary=source.summary,
            published_at_source=source.published_at,
        )
        try:
            draft = await create_draft(client, sessions, settings, draft_item)
        except DeepSeekBudgetExceeded as exc:
            logger.warning("DeepSeek daily limit reached while preparing /news: %s", str(exc))
            if not prepared:
                raise
            break
        except Exception as exc:
            # A single provider timeout, malformed answer or rejected RSS item
            # must not cancel the entire /news response. Try the next candidate.
            logger.warning(
                "Editorial API failed for one candidate (%s: %s)",
                exc.__class__.__name__,
                str(exc)[:180],
            )
            continue
        if draft.publish:
            prepared.append((draft.title, draft.body))
        if len(prepared) >= 3:
            break
    return _deduplicate_drafts(prepared)[:3]


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
                    if not drafts:
                        await _send_message(
                            client, token, chat_id,
                            "Пока не нашёл достаточно важных и неповторяющихся футбольных новостей. Попробуй позже командой /news.",
                        )
                    else:
                        await _send_message(client, token, chat_id, "⚽ <b>Главное в футболе</b>")
                        for title, body in drafts:
                            await _send_message(client, token, chat_id, _format_news_item(title, body))
                    logger.info("Prepared %d unique Russian football news stories for /news", len(drafts))
                except Exception as exc:
                    logger.warning("Could not prepare /news response (%s)", exc.__class__.__name__)
                    if isinstance(exc, DeepSeekBudgetExceeded):
                        error_text = "Сегодня исчерпан дневной лимит запросов или бюджета ИИ. Попробуй снова завтра."
                    else:
                        error_text = "Сейчас редактор ИИ временно недоступен. Я записал техническую причину в журнал приложения. Попробуй /news немного позже."
                    await _send_message(client, token, chat_id, error_text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram private bot polling failed (%s); retrying in 5 seconds", exc.__class__.__name__)
            await asyncio.sleep(5)
