"""Read player-card data from RenderZ's public, unauthenticated web pages.

This deliberately uses ordinary page URLs and server-rendered HTML. It does not
call undocumented/private endpoints, impersonate the mobile app, or bypass access
controls. Keep requests low-volume and cache results.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin

BASE_URL = "https://renderz.app"
PLAYERS_URL = BASE_URL + "/players"
CACHE_TTL = 600
NEGATIVE_CACHE_TTL = 45
log = logging.getLogger(__name__)
REQUEST_TIMEOUT = 18
MAX_RESULTS = 4

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = asyncio.Lock()


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._anchor_depth = 0
        self._anchor_href = ""
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            self._anchor_depth += 1
            if self._anchor_depth == 1:
                self._anchor_href = attrs.get("href", "")
                self._anchor_text = []

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._anchor_depth:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                label = " ".join(" ".join(self._anchor_text).split())
                if self._anchor_href and label:
                    self.links.append((self._anchor_href, label))
                self._anchor_href = ""
                self._anchor_text = []

    def handle_data(self, data):
        value = " ".join((data or "").split())
        if not value:
            return
        self.text.append(value)
        if self._anchor_depth:
            self._anchor_text.append(value)


def _parse_html(source: str) -> _PageText:
    parser = _PageText()
    parser.feed(source or "")
    parser.close()
    return parser


def _normalise_search_text(value: str) -> str:
    """Normalise accents, punctuation and case before comparing player names."""
    import unicodedata

    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold().replace("’", "'").replace(chr(96), "'")


def _search_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalise_search_text(value))


def _player_links(source: str, query: str) -> list[dict]:
    parser = _parse_html(source)
    requested_ovr_match = re.search(r"\b(\d{2,3})\b", query)
    requested_ovr = int(requested_ovr_match.group(1)) if requested_ovr_match else None
    query_tokens = [token for token in _search_tokens(query) if not token.isdigit()]
    # Require the complete player name, not a coincidental substring match.
    if not query_tokens:
        return []

    found = []
    seen = set()
    for href, label in parser.links:
        if not re.match(r"^/player/[A-Za-z0-9_-]+", href):
            continue
        full = urljoin(BASE_URL, href)
        label_tokens = _search_tokens(label)
        if not all(token in label_tokens for token in query_tokens):
            continue
        if full in seen:
            existing = next((item for item in found if item["url"] == full), None)
            duplicate_price = re.search(r"\b(\d+(?:\.\d+)?\s*[KMB])\b", label, re.I)
            if existing and duplicate_price and "market_price" not in existing:
                existing["market_price"] = duplicate_price.group(1).replace(" ", "")
            continue
        # Parse only values visibly present in RenderZ's public HTML.
        match = re.search(r"\b(\d{2,3})\s+(GK|CB|LB|RB|LWB|RWB|CDM|CM|CAM|LM|RM|LW|RW|CF|ST)\b", label, re.I)
        if not match:
            continue
        if requested_ovr is not None and int(match.group(1)) != requested_ovr:
            continue
        item = {
            "url": full,
            "label": label,
            "ovr": int(match.group(1)),
            "position": match.group(2).upper(),
        }
        market_price = re.search(r"\b(\d+(?:\.\d+)?\s*[KMB])\b", label, re.I)
        if market_price:
            item["market_price"] = market_price.group(1).replace(" ", "")
        for key, pattern in {
            "PAC": r"(\d{1,3})\s+PAC",
            "SHO": r"(\d{1,3})\s+SHO",
            "PAS": r"(\d{1,3})\s+PAS",
            "DRI": r"(\d{1,3})\s+DRI",
            "DEF": r"(\d{1,3})\s+DEF",
            "PHY": r"(\d{1,3})\s+PHY",
        }.items():
            value = re.search(pattern, label, re.I)
            if value:
                item[key] = int(value.group(1))
        seen.add(full)
        found.append(item)
    return found[:MAX_RESULTS]

def _detail_fields(source: str) -> dict:
    parser = _parse_html(source)
    text = " ".join(parser.text)
    result = {}
    heading = re.search(r"([^|]{2,90}?)\s*[—-]\s*(\d{2,3})\s*OVR", text, re.I)
    if heading:
        result["name"] = heading.group(1).strip()
        result["ovr"] = int(heading.group(2))
    for label, pattern in {
        "nation": r"NATION/REGION\s+([A-Za-zÀ-ÿ .'-]+?)(?=\s+(?:Skill Moves|STRONG FOOT|Height|Weight|Work Rate|Added on))",
        "height": r"Height\s+([^|]{1,30}?)(?=\s+Weight)",
        "weight": r"Weight\s+(\d{1,3}\s*kg)",
        "work_rate": r"Work Rate \(ATT\) / Work Rate \(DEF\)\s+([A-Za-z]+/[A-Za-z]+)",
        "added_on": r"Added on\s+(\d{1,2}/\d{1,2}/\d{4})",
    }.items():
        match = re.search(pattern, text, re.I)
        if match:
            result[label] = match.group(1).strip()
    program = re.search(r"Dislike\s+([A-Za-zÀ-ÿ0-9 '&-]{2,50}?)\s+Player", text)
    if program:
        result["program"] = program.group(1).strip()
    skill_moves = re.search(r"Skill Moves\s+\((\d)\)", text)
    if skill_moves:
        result["skill_moves"] = skill_moves.group(1)
    strong_foot = re.search(r"STRONG FOOT / WEAK FOOT\s+(RIGHT|LEFT)\s+/\s+\((\d)\)", text)
    if strong_foot:
        result["strong_foot"] = strong_foot.group(1) + " / weak " + strong_foot.group(2)
    playstyle_names = (
        "Relentless", "Anticipate", "First Touch", "Power Header", "Long Throw",
        "Trivela", "Finesse Shot", "Flair", "Aerial", "Quick Step", "Technical",
        "Press Proven", "Intercept", "Jockey", "Block", "Bruiser", "Tiki Taka",
        "Pinged Pass", "Whipped Pass", "Incisive Pass", "Long Ball Pass", "Dead Ball",
        "Chip Shot", "Power Shot", "Acrobatic", "Slide Tackle", "Enforcer",
        "Precision Header", "Rapid", "Trickster", "Low Driven Shot",
        "Long Shot Taker", "Acrobatic Clearance", "Roulette",
    )
    playstyles = [
        name for name in playstyle_names
        if re.search(r"\b" + re.escape(name) + r"\s+Level\s+[1-3]", text, re.I)
    ]
    if playstyles:
        result["playstyles"] = playstyles[:8]
    return result


def _format_card(card: dict, detail: dict | None = None) -> str:
    detail = detail or {}
    name = detail.get("name") or card["label"].split()
    if isinstance(name, list):
        name = " ".join(name[2:]) if len(name) > 2 else " ".join(name)
    lines = [
        f"• {name} — {card['ovr']} OVR, позиция {card['position']}",
        "  Характеристики: " + ", ".join(f"{k} {card[k]}" for k in ("PAC", "SHO", "PAS", "DRI", "DEF", "PHY") if k in card)
        if any(k in card for k in ("PAC", "SHO", "PAS", "DRI", "DEF", "PHY")) else "  Групповые характеристики в списке не указаны.",
    ]
    if card.get("market_price"):
        lines.append("  Цена рынка RenderZ: " + card["market_price"])
    if detail.get("program"):
        lines.append("  Программа: " + detail["program"])
    if detail.get("nation"):
        lines.append("  Страна: " + detail["nation"])
    if detail.get("skill_moves"):
        lines.append("  Финты: " + detail["skill_moves"] + "★")
    if detail.get("strong_foot"):
        lines.append("  Сильная нога / слабая нога: " + detail["strong_foot"])
    if detail.get("height"):
        lines.append("  Рост: " + detail["height"])
    if detail.get("weight"):
        lines.append("  Вес: " + detail["weight"])
    if detail.get("work_rate"):
        lines.append("  Work rate: " + detail["work_rate"])
    if detail.get("playstyles"):
        lines.append("  PlayStyles: " + ", ".join(detail["playstyles"]))
    if detail.get("added_on"):
        lines.append("  Карточка добавлена: " + detail["added_on"])
    lines.append("  Карточка: " + card["url"])
    return "\n".join(lines)


def _extract_search_query(message: str) -> str:
    value = re.sub(r"@\w+", " ", message or "")
    value = re.sub(
        r"(?i)\b(найди|покажи|скажи|расскажи|кто|такой|это|мне|или|и|что|за|лучше|какой|какая|какое|сколько|сравни|карточка|карточку|карты|карта|игрок|игрока|овр|ovr|рейтинг|статы|характеристики|цена|стоит|сейчас|у|на|в|по|для|fc\s*mobile|fcm|фкм|фк\s*мобайл|player|players|card|cards|stats|statistics|rating|overall|price|market|rank|training|compare|versus|vs|who|what|is|the|of|for|in|a|an)\b",
        " ", value,
    )
    value = re.sub(r"[^\w\s'-]", " ", value)
    value = " ".join(value.split())
    return value[:80]


def is_verified_player_context(context: str) -> bool:
    """True only when RenderZ returned at least one parsed player card."""
    return bool((context or "").startswith("ПРОВЕРЕННЫЕ ДАННЫЕ КАРТОЧЕК RENDERZ"))


def is_player_data_question(message: str) -> bool:
    text = (message or "").casefold()
    intent = re.search(
        r"(овр|\bovr\b|карточ|игрок|стат[ыи]|характеристик|ранг|прокач|трениров|цена|стоимост|сравни|лучше|"
        r"\bplayer\b|\bcards?\b|\bstats?\b|\bstatistics\b|\brating\b|\boverall\b|\bprice\b|\bmarket\b|\brank\b|\btraining\b|\bcompare\b|"
        r"месси|роналд|холанд|мбаппе|беллингем|винисиус|салах|кейн|ямал|неймар|эссьен|руни|фердинанд|"
        r"\bmessi\b|\bronald[o]?\b|\bhaaland\b|\bmbappe\b|\bbellingham\b|"
        r"\bvinicius\b|\bsalah\b|\bkane\b|\byamal\b|\bneymar\b|"
        r"\bde bruyne\b|\brodri\b|\bvan dijk\b|\bessien\b|\brooney\b|"
        r"\bferdinand\b|\bkaka\b|\beto'o\b|\bribery\b|\blahm\b|\bgarrincha\b|\bkvaratskhelia\b|\blampard\b|\bgerrard\b|\bzidane\b)",
        text,
    )
    has_card_rating = bool(re.search(r"\b(?:9[0-9]|1[0-3][0-9])\b", text))
    return bool(intent or has_card_rating)

async def _get_page(client, url: str) -> str:
    response = await client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; VasekFCMobileBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError("RenderZ вернул не HTML-страницу")
    return response.text


async def player_context(message: str, client) -> str:
    """Return source-grounded player data context, or an empty string."""
    if not is_player_data_question(message):
        return ""
    query = _extract_search_query(message)
    if len(query) < 2:
        return ""
    aliases = {
        "месси": "Messi", "роналду": "Ronaldo", "роналдо": "Ronaldo",
        "холанд": "Haaland", "холанда": "Haaland", "холанду": "Haaland",
        "мбаппе": "Mbappe", "беллингем": "Bellingham",
        "винисиус": "Vinicius", "винисиуса": "Vinicius",
        "салах": "Salah", "кейна": "Kane", "кейну": "Kane",
        "неймар": "Neymar", "неймара": "Neymar", "эссьен": "Essien",
        "руни": "Rooney", "фердинанд": "Ferdinand",
        "ван": "van", "дэйк": "Dijk", "де": "de", "брюйне": "Bruyne",
        "кварацхелия": "Kvaratskhelia", "кварацхелии": "Kvaratskhelia",
        "лэмпард": "Lampard", "джеррард": "Gerrard", "зидан": "Zidane",
        "кака": "Kaka", "лам": "Lahm", "рибери": "Ribery",
    }
    query_parts = query.split()
    search_parts = [aliases.get(part.casefold(), part) for part in query_parts]
    search_query = " ".join(search_parts)
    cache_key = query.casefold()
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached:
            ttl = CACHE_TTL if is_verified_player_context(cached[1]) else NEGATIVE_CACHE_TTL
            if time.monotonic() - cached[0] < ttl:
                return cached[1]

    # Use the public player-list page, not undocumented JSON/mobile endpoints.
    # The search parameter is a normal page URL; results are accepted only when
    # the returned visible card labels actually match the requested words.
    errors = []
    cards = []
    successful_fetch = False
    for url in (
        f"{PLAYERS_URL}?search={quote_plus(search_query)}",
        f"{PLAYERS_URL}?q={quote_plus(search_query)}",
        PLAYERS_URL,
    ):
        try:
            page = await _get_page(client, url)
            successful_fetch = True
            cards = _player_links(page, search_query)
            if cards:
                break
        except Exception as exc:
            errors.append(type(exc).__name__)

    if not cards:
        if successful_fetch:
            log.info("RenderZ pages loaded but no matching public card was parsed for query=%r", query)
            context = (
                "ДАННЫЕ RENDERZ: по запросу «" + query + "» карточка не найдена в публичном списке. "
                "Не выдумывай OVR, статы, ранг или цену. Уточни латинское написание имени либо версию карточки."
            )
        else:
            log.warning("RenderZ public player pages unavailable for query=%r; errors=%s", query, errors[:3])
            context = (
                "ДАННЫЕ RENDERZ: публичные страницы сейчас недоступны"
                + (" (" + ", ".join(errors[:3]) + ")" if errors else "")
                + ". Не выдумывай OVR, статы, ранг или цену; сообщи, что источник временно не ответил."
            )
        async with _cache_lock:
            _cache[cache_key] = (time.monotonic(), context)
        return context

    log.info("RenderZ parsed %s matching player card(s) for query=%r", len(cards), query)
    blocks = []
    # Fetch only the best matching page, keeping request volume low.
    for card in cards[:2]:
        detail = {}
        try:
            detail_page = await _get_page(client, card["url"])
            detail = _detail_fields(detail_page)
        except Exception:
            pass
        blocks.append(_format_card(card, detail))

    context = (
        "ПРОВЕРЕННЫЕ ДАННЫЕ КАРТОЧЕК RENDERZ (публичные страницы; время получения — "
        + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        + "). Это данные конкретных версий карт, не общий OVR состава. "
        "Используй только перечисленные поля; если запрошенное поле отсутствует, прямо скажи об этом. "
        "Не достраивай ранг, тренировку или рыночную цену догадкой.\n"
        + "\n".join(blocks)
    )
    async with _cache_lock:
        _cache[cache_key] = (time.monotonic(), context)
    return context
