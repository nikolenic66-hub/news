import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

os.environ.setdefault('DB_PATH', ':memory:')

from app import monitor
from app.monitor import extract_active_codes, parse_rss, _codes_from_recent_article


class MonitorParsingTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_only_active_codes(self):
        page = """
        <h2>Active Codes</h2>
        <div>COMINGHOME - England player pack</div>
        <div>CHOOSEYOURSIDE - Draft voucher</div>
        <h2>Expired Codes</h2>
        <div>AUTUMNCRUNCH</div>
        """
        self.assertEqual(
            extract_active_codes(page),
            ["COMINGHOME", "CHOOSEYOURSIDE"],
        )

    def test_does_not_guess_without_active_section(self):
        self.assertEqual(
            extract_active_codes("<p>New code: COMINGHOME</p>"),
            [],
        )

    def test_promo_code_article_must_be_recent(self):
        recent = format_datetime(datetime.now(timezone.utc) - timedelta(hours=3))
        stale = format_datetime(datetime.now(timezone.utc) - timedelta(days=30))
        base = {
            "title": "New FC Mobile redeem code: WINTER2026",
            "summary": "Redeem code WINTER2026 for rewards",
        }
        self.assertEqual(
            _codes_from_recent_article({**base, "published": recent}),
            ["WINTER2026"],
        )
        self.assertEqual(
            _codes_from_recent_article({**base, "published": stale}),
            [],
        )

    def test_promo_code_requires_explicit_new_code_language(self):
        recent = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertEqual(
            _codes_from_recent_article({
                "title": "FC Mobile gameplay update WINTER2026",
                "summary": "A new season is coming",
                "published": recent,
            }),
            [],
        )

    def test_rss_parser_reads_basic_items(self):
        feed = """<?xml version="1.0"?>
        <rss><channel><item>
          <title>FC Mobile update</title>
          <link>https://example.com/news</link>
          <description>New gameplay update</description>
          <pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate>
          <source>Example</source>
        </item></channel></rss>"""
        entries = parse_rss(feed)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "FC Mobile update")
        self.assertEqual(entries[0]["source"], "Example")


    async def test_question_context_refreshes_live_and_ignores_old_articles(self):
        from unittest.mock import AsyncMock, patch

        fresh_date = format_datetime(datetime.now(timezone.utc) - timedelta(hours=2))
        stale_date = format_datetime(datetime.now(timezone.utc) - timedelta(days=90))
        fresh = ("events_updates", "FC Mobile Rivals event guide", "New event rewards", "https://example.com/fresh", "Example", fresh_date)
        stale = ("official_news", "Old FIFA Mobile 2024 update", "Old data", "https://example.com/old", "Example", stale_date)

        with patch.object(monitor, "_last_on_demand_refresh", 0), \
             patch.object(monitor, "_last_question_refresh", 0), \
             patch.object(monitor, "check_news_once", new=AsyncMock()) as general_refresh, \
             patch.object(monitor, "_get_text", new=AsyncMock(return_value="<rss><channel></channel></rss>")) as fetch, \
             patch.object(monitor, "save_intel_item", new=AsyncMock()), \
             patch.object(monitor, "get_recent_intel", new=AsyncMock(return_value=[fresh, stale])), \
             patch.object(monitor, "get_recent_promo_codes", new=AsyncMock(return_value=[])):
            context = await monitor.build_intel_context("Что сейчас за событие?", object())

        general_refresh.assert_awaited_once()
        fetch.assert_awaited_once()
        self.assertIn("FC Mobile Rivals event guide", context)
        self.assertNotIn("Old FIFA Mobile 2024 update", context)
        self.assertIn("АКТУАЛЬНОСТЬ", context)
        self.assertIn("when%3A14d", fetch.await_args.args[1])

    async def test_empty_live_context_explicitly_rejects_old_knowledge(self):
        from unittest.mock import AsyncMock, patch

        with patch.object(monitor, "_last_on_demand_refresh", 10**12), \
             patch.object(monitor, "_last_question_refresh", 10**12), \
             patch.object(monitor, "get_recent_intel", new=AsyncMock(return_value=[])), \
             patch.object(monitor, "get_recent_promo_codes", new=AsyncMock(return_value=[])):
            context = await monitor.build_intel_context("Какие сейчас новые карты FC Mobile?")

        self.assertIn("СВЕЖИХ ПУБЛИКАЦИЙ НЕ НАЙДЕНО", context)
        self.assertIn("свежий факт сейчас подтвердить не удалось", context)

if __name__ == "__main__":
    unittest.main()
