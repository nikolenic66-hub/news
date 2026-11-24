import asyncio
import email.utils
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote_plus

from .storage import (
    get_recent_intel,
    get_recent_promo_codes,
    save_intel_item,
    save_promo_code,
)

log = logging.getLogger("vasek.monitor")

PROMO_CHECK_SECONDS = 8640  # 10 checks per day
NEWS_CHECK_SECONDS = 900  # refresh recent game news every 15 minutes
QUESTION_REFRESH_SECONDS = 90  # question-specific Google News lookup
_last_question_refresh = 0.0
REQUEST_HEADERS = {
    "User-Agent": "Vasek/1.0 (+FC Mobile community news monitor)",
    "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}

NEWS_FEEDS = (
    (
        "EA official FC Mobile news",
        "https://news.google.com/rss/search?q=site%3Aea.com%2Fgames%2Fea-sports-fc%2Ffc-mobile%2Fnews+when%3A7d&hl=en-US&gl=US&ceid=US:en",
        "official_news",
    ),
    (
        "FC Mobile updates, events and rewards",
        "https://news.google.com/rss/search?q=FC+Mobile+new+event+update+rewards+when%3A7d&hl=en-US&gl=US&ceid=US:en",
        "events_updates",
    ),
    (
        "FC Mobile cards, gameplay and meta",
        "https://news.google.com/rss/search?q=FC+Mobile+player+cards+gameplay+meta+when%3A7d&hl=en-US&gl=US&ceid=US:en",
        "gameplay_news",
    ),
    (
        "FC Mobile promo-code news",
        "https://news.google.com/rss/search?q=FC+Mobile+redeem+code+when%3A2d&hl=en-US&gl=US&ceid=US:en",
        "promo_news",
    ),
)

STOP_WORDS = {
    "FC", "MOBILE", "FCMOBILE", "ACTIVE", "EXPIRED", "CODES", "CODE", "REDEEM",
    "REWARDS", "REWARD", "LATEST", "NOVEMBER", "DECEMBER", "OCTOBER",
    "SEPTEMBER", "AUGUST", "JULY", "JUNE", "MAY", "APRIL", "MARCH",
    "FEBRUARY", "JANUARY", "STATUS", "PLAYER", "PLAYERS", "PACK",
    "PACKS", "ENGLAND", "SPAIN", "BRAZIL", "ARGENTINA", "GERMANY", "FRANCE", "ITALY", "PORTUGAL", "NETHERLANDS", "TURKEY", "MEXICO", "USA", "SHARDS", "POINTS", "HANDBOOK", "DRAFT", "VOUCHER", "VOUCHERS", "GEMS", "COINS",
    "UPDATED", "TODAY", "FREE", "OFFICIAL", "CLAIM", "CHECK",
    "AVAILABLE", "NEW", "ALL", "HOW", "WHERE", "THE", "AND",
}


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)


def html_to_text(source):
    parser = _VisibleText()
    try:
        parser.feed(source or "")
        parser.close()
        return " ".join(parser.parts)
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", source or ""))


def extract_active_codes(page_html):
    """Extract only codes inside an explicitly labelled active-code section."""
    text = html_to_text(page_html)
    normalized = re.sub(r"\s+", " ", text).strip()
    active = re.search(r"active\s+codes?", normalized, re.IGNORECASE)
    if not active:
        return []
    end = re.search(r"\bexpired\b", normalized[active.end():], re.IGNORECASE)
    section = normalized[active.end():active.end() + end.start()] if end else normalized[active.end():]
    candidates = re.findall(r"(?<![A-Z0-9])([A-Z][A-Z0-9]{5,23})(?![A-Z0-9])", section.upper())
    result = []
    for candidate in candidates:
        if candidate in STOP_WORDS or candidate.isdigit():
            continue
        if candidate not in result:
            result.append(candidate)
    return result


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_rss(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    entries = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        description = html_to_text(item.findtext("description") or "")
        published = (item.findtext("pubDate") or "").strip()
        source_node = item.find("source")
        source = (source_node.text or "").strip() if source_node is not None else "Google News"
        source_url = source_node.attrib.get("url", "").strip() if source_node is not None else ""
        if title and url:
            entries.append({
                "title": title[:500],
                "url": url,
                "summary": description[:2500],
                "published": published,
                "source": source[:100],
                "source_url": source_url[:1000],
            })
    return entries


def _is_disallowed_source(entry):
    """Exclude RenderZ until written permission for this bot use is obtained."""
    source = (entry.get("source") or "").lower()
    source_url = (entry.get("source_url") or "").lower()
    article_url = (entry.get("url") or "").lower()
    restricted_markers = ("renderz", "fcmhub", "fc mobile forum", "fcmobileforum", "fcindex")
    combined = " ".join((source, source_url, article_url))
    return any(marker in combined for marker in restricted_markers)


def _codes_from_recent_article(entry):
    """Accept code candidates only from genuinely recent, explicitly code-related articles."""
    published = _parse_date(entry.get("published"))
    if not published:
        return []
    age_seconds = (datetime.now(timezone.utc) - published).total_seconds()
    # Old articles and implausibly future-dated items must never trigger alerts.
    if age_seconds < -2 * 3600 or age_seconds > 48 * 3600:
        return []
    title = entry.get("title", "")
    text = title + " " + entry.get("summary", "")
    if not re.search(r"\b(redeem\s+code|promo\s+code|new\s+code|code\s+released|code\s+available)\b", text, re.IGNORECASE):
        return []
    candidates = re.findall(r"(?<![A-Z0-9])([A-Z][A-Z0-9]{5,23})(?![A-Z0-9])", text.upper())
    return [c for c in dict.fromkeys(candidates) if c not in STOP_WORDS]


async def _get_text(client, url):
    response = await client.get(url, headers=REQUEST_HEADERS, follow_redirects=True)
    response.raise_for_status()
    return response.text


async def check_promo_codes_once(client, send_alert):
    """Alert only on codes mentioned in dated, recent promo-code articles.

    Static code-list pages are deliberately not used for alerts: they often retain
    old codes and provide no trustworthy publication/creation timestamp.
    """
    new_codes = 0
    for source_name, url, kind in NEWS_FEEDS:
        if kind != "promo_news":
            continue
        try:
            feed = await _get_text(client, url)
            for entry in parse_rss(feed):
                for code in _codes_from_recent_article(entry):
                    inserted = await save_promo_code(code, source_name, entry["url"])
                    if inserted:
                        new_codes += 1
                        await send_alert(
                            "🚨 Возможный новый промокод FC Mobile: " + code + "\n"
                            "Дата публикации: " + (entry.get("published") or "не указана") + "\n"
                            "Публикация: " + entry["title"][:250] + "\n"
                            "Источник: " + entry["url"] + "\n"
                            "Активировать: https://redeem.fcm.ea.com/\n"
                            "Код найден в свежей публикации за последние 48 часов; действительность проверь на странице EA."
                        )
        except Exception:
            log.exception("Promo-code feed failed: %s", source_name)
    return new_codes


async def check_news_once(client):
    """Collect current FC Mobile news without running promo-code scans."""
    for source_name, url, kind in NEWS_FEEDS:
        if kind == "promo_news":
            continue
        try:
            feed = await _get_text(client, url)
            for entry in parse_rss(feed):
                if _is_disallowed_source(entry):
                    continue
                published_dt = _parse_date(entry["published"])
                if not published_dt:
                    continue
                age_seconds = (datetime.now(timezone.utc) - published_dt).total_seconds()
                if age_seconds > 14 * 24 * 3600 or age_seconds < -6 * 3600:
                    continue
                await save_intel_item(
                    kind,
                    entry["url"],
                    entry["title"],
                    entry["summary"],
                    entry["url"],
                    entry["source"] or source_name,
                    entry["published"],
                )
        except Exception:
            log.exception("News feed failed: %s", source_name)


async def monitor_loop(client, send_alert):
    log.info(
        "FC Mobile monitor started; promo codes every %s seconds (10/day), news every %s seconds",
        PROMO_CHECK_SECONDS,
        NEWS_CHECK_SECONDS,
    )
    next_promo = 0.0
    next_news = 0.0
    loop = asyncio.get_running_loop()
    while True:
        now = loop.time()
        if now >= next_promo:
            try:
                count = await check_promo_codes_once(client, send_alert)
                if count:
                    log.info("FC Mobile monitor discovered %s new promo code(s)", count)
            except Exception:
                log.exception("Promo-code monitor cycle failed")
            next_promo = loop.time() + PROMO_CHECK_SECONDS
        now = loop.time()
        if now >= next_news:
            try:
                await check_news_once(client)
            except Exception:
                log.exception("FC Mobile news monitor cycle failed")
            next_news = loop.time() + NEWS_CHECK_SECONDS
        await asyncio.sleep(max(1, min(next_promo, next_news) - loop.time()))


async def build_intel_context(query, client=None):
    global _last_question_refresh
    is_game_query = bool(re.search(
        r"fc\s*mobile|фк\s*мобайл|промокод|\bкод\b|карточк|овр|состав|"
        r"событи|обновлени|патч|тактик|мета|игрок|награ|магазин|обмен|"
        r"что сейчас|сегодня|последн|свеже|актуальн|какой ивент|какое событие|новый ивент|новые карты",
        query or "",
        re.IGNORECASE,
    ))
    if not is_game_query:
        return ""
    now = time.monotonic()
    # Also run a query-specific Google News RSS search so a question about a
    # particular event/player/update is not limited to the static feed topics.
    if client is not None and now - _last_question_refresh >= QUESTION_REFRESH_SECONDS:
        _last_question_refresh = now
        search_terms = re.sub(r"[^\w\s-]", " ", query or "", flags=re.UNICODE)
        search_terms = re.sub(r"\s+", " ", search_terms).strip()[:100]
        if search_terms:
            search_url = (
                "https://news.google.com/rss/search?q="
                + quote_plus("FC Mobile " + search_terms + " when:14d")
                + "&hl=en-US&gl=US&ceid=US:en"
            )
            try:
                feed = await _get_text(client, search_url)
                current_time = datetime.now(timezone.utc)
                for entry in parse_rss(feed):
                    if _is_disallowed_source(entry):
                        continue
                    published = _parse_date(entry.get("published"))
                    if not published or not (-6 * 3600 <= (current_time - published).total_seconds() <= 7 * 24 * 3600):
                        continue
                    await save_intel_item(
                        "question_search", entry["url"], entry["title"],
                        entry["summary"], entry["url"], entry["source"], entry["published"],
                    )
            except Exception:
                log.exception("Question-specific FC Mobile news search failed")
    news = await get_recent_intel(20)
    codes = await get_recent_promo_codes(8)
    current = datetime.now(timezone.utc)
    fresh_news = []
    for item in news:
        published = _parse_date(item[5])
        if published and -6 * 3600 <= (current - published).total_seconds() <= 7 * 24 * 3600:
            fresh_news.append(item)
    lines = [
        "АКТУАЛЬНОСТЬ: текущая дата UTC " + current.strftime("%Y-%m-%d %H:%M") + ".",
        "Ниже — свежие внешние публикации FC Mobile, собранные монитором прямо перед ответом или недавно. Используй их для вопросов о текущих событиях, обновлениях, карточках и мета.",
        "У каждой публикации есть дата. Считай её старой, если она старше 7 дней. Не подменяй отсутствие свежих данных знаниями из FIFA Mobile 2023/2024.",
        "Разделяй официальные публикации EA и материалы сообщества. Не выдавай прогнозы и слухи за подтверждённые факты.",
    ]
    if codes:
        lines.append("Промокоды, замеченные недавно (валидность EA автоматически не проверяется):")
        for code, reward, source, url, first_seen in codes:
            lines.append(f"- {code}; источник: {source}; впервые замечен: {first_seen}; {url}")
    if fresh_news:
        lines.append("СВЕЖИЕ ПУБЛИКАЦИИ:")
        for kind, title, summary, url, source, published, fetched_at in fresh_news:
            detail = (summary or "").strip()
            source_label = (
                "EA — источник из официальной ленты"
                if kind == "official_news" and "ea" in (source or "").lower()
                else "сообщество/вторичный источник"
            )
            lines.append(
                f"- [{kind}; уровень: {source_label}] {title} "
                f"(источник: {source}; опубликовано: {published}; получено ботом: {fetched_at} UTC). "
                f"{detail[:500]} Ссылка: {url}"
            )
    else:
        lines.append("СВЕЖИХ ПУБЛИКАЦИЙ НЕ НАЙДЕНО. Не называй старые сведения актуальными; честно скажи, что свежий факт сейчас подтвердить не удалось.")
    return "\n".join(lines)[:9000]



def format_news_digest(items, limit=6, now=None):
    """Format only dated FC Mobile publications no older than seven days."""
    now = now or datetime.now(timezone.utc)
    lines = []
    for item in items:
        if len(item) < 7:
            continue
        kind, title, summary, url, source, published_at, fetched_at = item[:7]
        published = _parse_date(published_at)
        if not published:
            continue
        age = (now - published).total_seconds()
        if age < -6 * 3600 or age > 7 * 24 * 3600:
            continue
        stamp = published.strftime("%d.%m %H:%M UTC")
        lines.append(f"• {title} — {source}, {stamp}\n{url}")
        if len(lines) >= max(1, min(10, int(limit))):
            break
    return "\n\n".join(lines) if lines else "Свежих публикаций за последние 7 дней пока нет. Не буду подсовывать старые новости."


def format_sources_status(items, limit=8):
    """Show the latest stored source records and their publication/fetch times."""
    seen = set()
    lines = []
    for item in items:
        if len(item) < 7:
            continue
        kind, title, summary, url, source, published_at, fetched_at = item[:7]
        key = (kind, source)
        if key in seen:
            continue
        seen.add(key)
        label = "EA / официальный поиск" if kind == "official_news" and "ea" in (source or "").lower() else "сообщество / вторичный"
        lines.append(f"• {source} ({label})\nПоследняя публикация: {published_at or 'дата неизвестна'}\nПолучено ботом: {fetched_at} UTC")
        if len(lines) >= max(1, min(12, int(limit))):
            break
    return "\n\n".join(lines) if lines else "Источники пока не прислали ни одной записи."
