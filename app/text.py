"""Deterministic text sanitation after AI generation."""
from __future__ import annotations

import html
import re

AI_CLICHES = (
    "стоит отметить",
    "следует отметить",
    "нельзя не отметить",
    "мир футбола не перестает удивлять",
    "мир футбола не перестаёт удивлять",
    "мир футбола продолжает удивлять",
    "это по-настоящему громкое событие",
    "подводя итог",
)


def clean_text(value: str) -> str:
    value = value.replace("\\u00a0", " ").replace("\\u200b", "")
    # The channel style deliberately avoids typographic long dashes.
    value = value.replace("\\u2014", " - ").replace("\\u2013", " - ").replace("\\u2212", "-")
    value = re.sub(r"[ \\t]+", " ", value)
    value = re.sub(r" *\\n[ \\t]*", "\\n", value)
    value = re.sub(r"\\n{3,}", "\\n\\n", value)
    value = re.sub(r"\\s+([,.;:!?])", r"\\1", value)
    value = re.sub(r"([,;:])(?=\\S)", r"\\1 ", value)
    return value.strip(" \\n\\t-")


def contains_ai_cliche(value: str) -> bool:
    lowered = value.casefold().replace("ё", "е")
    return any(phrase.casefold().replace("ё", "е") in lowered for phrase in AI_CLICHES)


def truncate_on_word(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    fragment = value[: max(1, max_chars - 1)]
    last_space = fragment.rfind(" ")
    if last_space > max_chars * 0.65:
        fragment = fragment[:last_space]
    return fragment.rstrip(" ,;:-") + "…"


def build_caption(title: str, body: str, source_name: str, source_url: str,
                  photo_author: str, photo_license: str, photo_license_url: str,
                  photo_page_url: str, illustrative: bool) -> str:
    safe_title = html.escape(truncate_on_word(clean_text(title), 150), quote=False)
    source_label = html.escape(truncate_on_word(clean_text(source_name or "Источник"), 80), quote=False)
    source_link = html.escape(source_url, quote=True)
    author = html.escape(truncate_on_word(clean_text(photo_author or "Автор не указан"), 150), quote=False)
    license_label = html.escape(truncate_on_word(clean_text(photo_license or "Лицензия"), 80), quote=False)
    license_link = html.escape(photo_license_url or photo_page_url, quote=True)
    image_link = html.escape(photo_page_url, quote=True)

    source_line = f'Источник: <a href="{source_link}">{source_label}</a>'
    photo_line = f'Фото: <a href="{image_link}">{author}</a> · <a href="{license_link}">{license_label}</a> · Wikimedia Commons'
    if illustrative:
        photo_line += "\\nФото иллюстративное."

    raw_body = clean_text(body)

    def compose(candidate_body: str) -> str:
        safe_body = html.escape(candidate_body, quote=False)
        return f"<b>{safe_title}</b>\\n\\n{safe_body}\\n\\n{source_line}\\n{photo_line}"

    # Iterate on the unescaped body because HTML entities add characters to the payload.
    candidate = truncate_on_word(raw_body, 650)
    caption = compose(candidate)
    while len(caption) > 1000 and candidate:
        overage = len(caption) - 980
        candidate = truncate_on_word(candidate, max(0, len(candidate) - max(overage, 30)))
        caption = compose(candidate)
    if len(caption) > 1024:
        # Defensive fallback: preserve source and license attribution instead of cutting HTML tags.
        candidate = ""
        caption = compose(candidate)
    if len(caption) > 1024:
        raise ValueError("Caption and mandatory source/photo attribution exceed Telegram's limit")
    return caption
