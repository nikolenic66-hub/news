from app.text import build_caption, clean_text, contains_ai_cliche, truncate_on_word


def test_clean_text_removes_typographic_long_dashes():
    result = clean_text("Трансфер — важный шаг – для клуба")
    assert "—" not in result
    assert "–" not in result
    assert result == "Трансфер - важный шаг - для клуба"


def test_clean_text_normalizes_whitespace():
    assert clean_text("  Первый   абзац.  \n\n\n  Второй  ") == "Первый абзац.\n\nВторой"


def test_ai_cliche_detection():
    assert contains_ai_cliche("Стоит отметить, что это важно")
    assert not contains_ai_cliche("Клуб объявил о подписании игрока")


def test_truncate_on_word_does_not_exceed_limit():
    result = truncate_on_word("Слова для аккуратного сокращения длинного текста", 24)
    assert len(result) <= 24
    assert result.endswith("…")


def test_caption_escapes_html_and_keeps_attribution():
    caption = build_caption(
        title='Клуб <"А" и "Б"> подписал игрока',
        body="Клуб объявил о соглашении с футболистом. Подробности опубликованы в сообщении команды.",
        source_name="Официальный сайт клуба",
        source_url="https://example.org/news?a=1&b=2",
        photo_author="Photo Author",
        photo_license="CC BY-SA 4.0",
        photo_license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        photo_page_url="https://commons.wikimedia.org/wiki/File:Example.jpg",
        illustrative=True,
    )
    assert len(caption) <= 1024
    assert "<b>" in caption and "</b>" in caption
    assert "Wikimedia Commons" in caption
    assert "Фото иллюстративное" in caption
    assert "&lt;" in caption
    assert " — " not in caption
