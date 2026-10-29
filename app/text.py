"""Deterministic text sanitation after AI generation."""
from __future__ import annotations

import html
import re

AI_CLICHES = (
    "стоит отметить",
    "следует отметить",
    "нельзя не отметить",
    "мир футбола не перестает удивлять",
    "мир футбола продолжает удивлять",
    "это по-настоящему громкое событие",
    "подводя итог",
)


def clean_text(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    # The channel style deliberately avoids typographic long dashes.
    value = value.replace("\u2014", " - ").replace("\u2013", " - ").replace("\u2212", "-")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n[ \t]*", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"([,;:])(?=\S)", r"\1 ", value)
    return value.strip(" \n\t-")


def contains_ai_cliche(value: str) -> bool:
    lowered = value.casefold()
    return any(phrase in lowered for phrase in AI_CLICHES)


def truncate_on_word(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    fragment = value[: max_chars - 1]
    last_space = fragment.rfind(" ")
    if last_space > max_chars * 0.65:
        fragment = fragment[:last_space]
    return fragment.rstrip(" ,;:-") + "…"


def build_caption(title: str, body: str, source_name: str, source_url: str,
                  photo_author: str, photo_license: str, photo_license_url: str,
                  photo_page_url: str, illustrative: bool) -> str:
    safe_title = html.escape(clean_text(title), quote=False)
    safe_body = html.escape(clean_text(body), quote=False)
    source_label = html.escape(clean_text(source_name or "Источник"), quote=False)
    source_link = html.escape(source_url, quote=True)
    author = html.escape(clean_text(photo_author or "Автор не указан"), quote=False)
    license_label = html.escape(clean_text(photo_license or "Лицензия"), quote=False)
    license_link = html.escape(photo_license_url or photo_page_url, quote=True)
    image_link = html.escape(photo_page_url, quote=True)

    source_line = f'Источник: <a href="{source_link}">{source_label}</a>'
    photo_line = f'Фото: <a href="{image_link}">{author}</a> · <a href="{license_link}">{license_label}</a> · Wikimedia Commons'
    if illustrative:
        photo_line += "\nФото иллюстративное."

    # Telegram photo captions are limited. Keep room for links and required photo credit.
    fixed = f"<b>{safe_title}</b>\n\n\n{source_line}\n{photo_line}"
    budget = max(0, 1000 - len(fixed) - 2)
    safe_body = html.escape(truncate_on_word(clean_text(body), budget), quote=False)
    caption = f"<b>{safe_title}</b>\n\n{safe_body}\n\n{source_line}\n{photo_line}"
    return caption[:1024]
