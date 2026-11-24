import asyncio
import email.utils
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

from .storage import (
    get_recent_intel,
    get_recent_promo_codes,
    save_intel_item,
    save_promo_code,
)

log = logging.getLogger("fc-mate.monitor")

POLL_SECONDS = 300
REQUEST_HEADERS = {
    "User-Agent": "FC-Mate/1.0 (+FC Mobile community news monitor)",
    "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}

CODE_PAGES = (
    ("FCMobileForum", "https://www.fcmobileforum.com/fcmobile-redeem-codes"),
    ("FC Mobile Squad", "https://fcmobilesquad.com/redeem-code"),
    ("Mr Believer Hub", "https://mrbelieverhub.com/fcmobile-redeem-codes"),
)

NEWS_FEEDS = (
    (
        "EA official news via Google News RSS",
        "https://news.google.com/rss/search?q=site%3Aea.com%2Fgames%2Fea-sports-fc%2Ffc-mobile%2Fnews&hl=en-US&gl=US&ceid=US:en",
        "official_news",
    ),
    (
        "FC Mobile promo-code news",
        "https://news.google.com/rss/search?q=FC+Mobile+redeem+code&hl=en-US&gl=US&ceid=US:en",
        "promo_news",
    ),
    (
        "FC Mobile cards and meta",
        "https://news.google.com/rss/search?q=FC+Mobile+player+cards+RenderZ+meta&hl=en-US&gl=US&ceid=US:en",
        "gameplay_news",
    ),
)

STOP_WORDS = {
    "FC", "MOBILE", "FCMOBILE", "ACTIVE", "EXPIRED", "CODES", "CODE", "REDEEM",
    "REWARDS", "REWARD", "LATEST", "NOVEMBER", "DECEMBER", "OCTOBER",
    "SEPTEMBER", "AUGUST", "JULY", "JUNE", "MAY", "APRIL", "MARCH",
    "FEBRUARY", "JANUARY", "STATUS", "PLAYER", "PLAYERS", "PACK",
    "PACKS", "DRAFT", "VOUCHER", "VOUCHERS", "GEMS", "COINS",
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
        if title and url:
            entries.append({
                "title": title[:500],
                "url": url,
                "summary": description[:2500],
                "published": published,
                "source": source[:100],
            })
    return entries


def _codes_from_recent_article(entry):
    published = _parse_date(entry.get("published"))
    if not published or (datetime.now(timezone.utc) - published).total_seconds() > 72 * 3600:
        return []
    text = entry.get("title", "") + " " + entry.get("summary", "")
    if not re.search(r"\b(code|redeem|promo)\b", text, re.IGNORECASE):
        return []
    candidates = re.findall(r"(?<![A-Z0-9])([A-Z][A-Z0-9]{5,23})(?![A-Z0-9])", text.upper())
    return [c for c in dict.fromkeys(candidates) if c not in STOP_WORDS]


async def _get_text(client, url):
    response = await client.get(url, headers=REQUEST_HEADERS, follow_redirects=True)
    response.raise_for_status()
    return response.text


async def monitor_once(client, send_alert):
    """Poll sources once. Alerts are sent only for codes not seen in the database."""
    new_codes = 0
    for source, url in CODE_PAGES:
        try:
            page = await _get_text(client, url)
            codes = extract_active_codes(page)
            for code in codes:
                inserted = await save_promo_code(code, source, url)
                if inserted:
                    new_codes += 1
                    alert = (
                        "🚨 Новый код FC Mobile: " + code + "\n"
                        "Источник: " + source + "\n"
                        "Проверяй и активируй сразу: https://redeem.fcm.ea.com/\n"
                        "Важно: код найден в активном списке сообщества; EA не подтверждает его статус автоматически. "
                        "Коды могут быстро истечь или закончиться."
                    )
                    await send_alert(alert)
        except Exception:
            log.exception("Promo-code source failed: %s", source)

    for source_name, url, kind in NEWS_FEEDS:
        try:
            feed = await _get_text(client, url)
            for entry in parse_rss(feed):
                await save_intel_item(
                    kind,
                    entry["url"],
                    entry["title"],
                    entry["summary"],
                    entry["url"],
                    entry["source"] or source_name,
                    entry["published"],
                )
                for code in _codes_from_recent_article(entry):
                    inserted = await save_promo_code(code, source_name, entry["url"])
                    if inserted:
                        new_codes += 1
                        await send_alert(
                            "🚨 Похоже, появился новый промокод FC Mobile: " + code + "\n"
                            "Нашёл публикацию: " + entry["title"][:250] + "\n"
                            "Источник: " + entry["url"] + "\n"
                            "Проверь и активируй: https://redeem.fcm.ea.com/\n"
                            "Статус пока не подтверждён EA."
                        )
        except Exception:
            log.exception("News feed failed: %s", source_name)
    return new_codes


async def monitor_loop(client, send_alert):
    log.info("FC Mobile monitor started; polling every %s seconds", POLL_SECONDS)
    while True:
        try:
            count = await monitor_once(client, send_alert)
            if count:
                log.info("FC Mobile monitor discovered %s new promo code(s)", count)
        except Exception:
            log.exception("FC Mobile monitor cycle failed")
        await asyncio.sleep(POLL_SECONDS)


async def build_intel_context(query):
    if not re.search(
        r"fc\s*mobile|фк\s*мобайл|промокод|\bкод\b|карточк|овр|состав|"
        r"событи|обновлени|патч|тактик|мета|игрок",
        query or "",
        re.IGNORECASE,
    ):
        return ""
    news = await get_recent_intel(8)
    codes = await get_recent_promo_codes(8)
    if not news and not codes:
        return ""
    lines = [
        "Свежая справка из мониторинга FC Mobile. Это внешние публикации, а не гарантированно подтверждённые факты.",
        "Проверяй даты и статус; не называй слух официальной информацией.",
    ]
    if codes:
        lines.append("Недавно замеченные промокоды (статус EA автоматически не проверяется):")
        for code, reward, source, url, first_seen in codes:
            lines.append(f"- {code}; источник: {source}; впервые замечен: {first_seen}; {url}")
    if news:
        lines.append("Последние публикации:")
        for kind, title, summary, url, source, published in news:
            detail = (summary or "").strip()
            lines.append(f"- [{kind}] {title} ({source}; {published or 'дата не указана'}). {detail[:350]} Ссылка: {url}")
    return "\n".join(lines)[:6500]
