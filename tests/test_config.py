from app.config import Settings


def _clear_app_env(monkeypatch):
    for name in (
        "DATABASE_URL", "APP_MODE", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "DEEPSEEK_DAILY_BUDGET_USD", "MAX_DEEPSEEK_CALLS_PER_DAY",
        "RSS_FEEDS", "MAX_POSTS_PER_DAY", "DB_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_safe_default_collect_only_needs_only_database(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/news")
    monkeypatch.setenv("RSS_FEEDS", "https://example.org/rss")
    settings = Settings.from_env()
    assert settings.app_mode == "collect_only"
    assert settings.max_posts_per_day <= 10
    assert settings.max_deepseek_calls_per_day == 30
    assert str(settings.deepseek_daily_budget_usd) == "0.08"
    settings.validate_runtime()


def test_live_mode_fails_fast_without_telegram_and_deepseek_keys(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/news")
    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("RSS_FEEDS", "https://example.org/rss")
    settings = Settings.from_env()
    try:
        settings.validate_runtime()
    except RuntimeError as exc:
        message = str(exc)
        assert "DEEPSEEK_API_KEY" in message
        assert "TELEGRAM_BOT_TOKEN" in message
        assert "TELEGRAM_CHANNEL_ID" in message
    else:
        raise AssertionError("Live mode must require keys")


def test_post_limit_is_clamped_to_ten(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("MAX_POSTS_PER_DAY", "1000")
    settings = Settings.from_env()
    assert settings.max_posts_per_day == 10


def test_history_retention_defaults_to_four_months(monkeypatch):
    _clear_app_env(monkeypatch)
    settings = Settings.from_env()
    assert settings.db_retention_days == 120
