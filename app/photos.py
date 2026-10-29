"""Search Wikimedia Commons and only accept clearly reusable image licenses."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

logger = logging.getLogger(__name__)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
STOP_WORDS = {
    "the", "and", "with", "from", "football", "soccer", "match", "player", "players",
    "association", "action", "photo", "image", "club", "team", "news", "official",
}


@dataclass(frozen=True, slots=True)
class LicensedPhoto:
    image_url: str
    page_url: str
    author: str
    license_name: str
    license_url: str
    illustrative: bool


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))).strip()


def _license_is_redistributable(value: str) -> bool:
    licence = _plain(value).strip().upper()
    if not licence or any(token in licence for token in ("NONCOMMERCIAL", "NC-", "NC " , "FAIR USE")):
        return False
    return (
        licence.startswith("CC BY-SA ") or
        licence.startswith("CC BY ") or
        licence.startswith("CC0") or
        licence.startswith("PUBLIC DOMAIN") or
        licence.startswith("PD-")
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) > 2 and token not in STOP_WORDS}


def _metadata_value(ext: dict, key: str) -> str:
    field = ext.get(key) or {}
    if isinstance(field, dict):
        return _plain(str(field.get("value", "")))
    return _plain(str(field))


async def _search_once(client: httpx.AsyncClient, settings: Settings, query: str, *, illustrative_if_weak: bool) -> LicensedPhoto | None:
    response = await client.get(
        COMMONS_API,
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1280,
        },
        headers={"User-Agent": settings.wikimedia_user_agent, "Accept": "application/json"},
        timeout=httpx.Timeout(25.0, connect=10.0),
    )
    response.raise_for_status()
    payload = response.json()
    pages = list((payload.get("query", {}).get("pages") or {}).values())
    wanted = _tokens(query)
    best: tuple[int, LicensedPhoto] | None = None

    for page in pages:
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = str(info.get("mime", "")).lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        image_url = str(info.get("thumburl") or info.get("url") or "")
        page_url = str(info.get("descriptionurl") or "")
        if urlsplit(image_url).hostname != "upload.wikimedia.org":
            continue
        if urlsplit(page_url).hostname != "commons.wikimedia.org":
            continue

        ext = info.get("extmetadata") or {}
        licence = _metadata_value(ext, "LicenseShortName")
        if not _license_is_redistributable(licence):
            continue
        licence_url = str((ext.get("LicenseUrl") or {}).get("value") or page_url)
        parsed_license_url = urlsplit(licence_url)
        if parsed_license_url.scheme == "http" and parsed_license_url.hostname:
            # Commons metadata still contains some legacy http:// Creative Commons links.
            licence_url = parsed_license_url._replace(scheme="https").geturl()
        if urlsplit(licence_url).scheme != "https":
            licence_url = page_url
        author = _metadata_value(ext, "Artist") or _metadata_value(ext, "Credit")
        needs_attribution = licence.upper().startswith(("CC BY ", "CC BY-SA "))
        if needs_attribution and not author:
            # Do not publish an attribution-required image when the author cannot be identified.
            continue
        author = author or "Автор не указан"
        description = _metadata_value(ext, "ImageDescription")
        meta_text = f"{page.get('title', '')} {description}"
        overlap = len(wanted & _tokens(meta_text))
        needed = 2 if len(wanted) >= 3 else (1 if wanted else 0)
        # If the query contains no distinguishing terms, this is a generic illustration, not an event-specific photo.
        weak_match = not wanted or overlap < needed
        photo = LicensedPhoto(
            image_url=image_url,
            page_url=page_url,
            author=author[:500],
            license_name=licence[:200],
            license_url=licence_url,
            illustrative=illustrative_if_weak or weak_match,
        )
        score = overlap
        if best is None or score > best[0]:
            best = (score, photo)
        if not weak_match and not illustrative_if_weak:
            return photo

    return best[1] if best else None


async def find_licensed_photo(client: httpx.AsyncClient, settings: Settings, query: str) -> LicensedPhoto | None:
    query = re.sub(r"[^\w\s'-]", " ", query, flags=re.UNICODE)
    query = re.sub(r"\s+", " ", query).strip()[:180]
    if query:
        try:
            result = await _search_once(client, settings, query, illustrative_if_weak=False)
            if result and not result.illustrative:
                return result
            if result:
                best_specific = result
            else:
                best_specific = None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Wikimedia search failed: %s", exc.__class__.__name__)
            best_specific = None
    else:
        best_specific = None

    # A generic licensed football photo is acceptable only when clearly labelled illustrative.
    try:
        generic = await _search_once(
            client, settings, "association football players match", illustrative_if_weak=True
        )
        if generic:
            return generic
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Wikimedia fallback search failed: %s", exc.__class__.__name__)
    return best_specific
