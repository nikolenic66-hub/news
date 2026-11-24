import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_PATH", ":memory:")

import httpx
from app import monitor


class RSSResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_rss_retries_503_and_recovers(self):
        request = httpx.Request("GET", "https://news.google.com/rss")
        unavailable = httpx.Response(503, request=request)
        recovered = httpx.Response(200, request=request, text="<rss><channel/></rss>")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[unavailable, unavailable, recovered])

        with patch.object(monitor.asyncio, "sleep", new=AsyncMock()):
            text = await monitor._get_text(client, "https://news.google.com/rss?q=FC+Mobile")

        self.assertIn("<rss>", text)
        self.assertEqual(client.get.await_count, 3)

    async def test_bing_rss_fallback_used_after_google_outage(self):
        google_request = httpx.Request("GET", "https://news.google.com/rss")
        bing_request = httpx.Request("GET", "https://www.bing.com/news/search")
        unavailable = httpx.Response(503, request=google_request)
        fallback = httpx.Response(200, request=bing_request, text="<rss><channel/></rss>")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[unavailable, unavailable, unavailable, fallback])

        with patch.object(monitor.asyncio, "sleep", new=AsyncMock()):
            text = await monitor._get_text(client, "https://news.google.com/rss?q=FC+Mobile+news")

        self.assertIn("<rss>", text)
        self.assertEqual(client.get.await_count, 4)
        self.assertIn("bing.com/news/search", client.get.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
