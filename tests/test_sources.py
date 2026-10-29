from app.sources import canonicalize_url, html_to_text


def test_canonicalize_url_drops_tracking_parameters_and_fragment():
    result = canonicalize_url("https://Example.org/news/123?utm_source=test&id=7&fbclid=xyz#part")
    assert result == "https://example.org/news/123?id=7"


def test_reject_non_http_urls():
    assert canonicalize_url("javascript:alert(1)") == ""
    assert canonicalize_url("not-a-url") == ""


def test_html_to_text_strips_markup():
    assert html_to_text("<p>Клуб <b>объявил</b> о сделке&nbsp;с игроком.</p>") == "Клуб объявил о сделке с игроком."
