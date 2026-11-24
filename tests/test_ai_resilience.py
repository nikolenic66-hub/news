import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_PATH", ":memory:")

from app import ai


class AIResilienceTests(unittest.IsolatedAsyncioTestCase):
    def test_prompt_bounds_preserve_persona_and_limit_context(self):
        messages = [
            {"role": "system", "content": "persona-" + "P" * 5000},
            {"role": "system", "content": "context-" + "C" * 3000},
            *[{"role": "user", "content": "message-" + "M" * 1200} for _ in range(12)],
        ]
        bounded = ai._bounded_messages(messages)
        self.assertEqual(bounded[0]["role"], "system")
        self.assertTrue(bounded[0]["content"].startswith("persona-"))
        self.assertLessEqual(len(bounded[0]["content"]), 14000)
        self.assertLessEqual(len(bounded[-1]["content"]), 650)
        self.assertLessEqual(len([m for m in bounded if m["role"] != "system"]), 8)

    async def test_429_retries_once_then_succeeds_and_caps_output(self):
        import httpx

        request = httpx.Request("POST", "https://example.test")
        rate_limited = httpx.Response(
            429,
            request=request,
            headers={"retry-after": "0"},
            text='{"error":{"message":"Rate limit reached. Please try again in 0.1s"}}',
        )
        success = httpx.Response(200, request=request, json={"choices": [{"message": {"content": "ok"}}]})
        client_instance = AsyncMock()
        client_instance.__aenter__.return_value = client_instance
        client_instance.__aexit__.return_value = False
        client_instance.post = AsyncMock(side_effect=[rate_limited, success])

        with patch.object(ai, "GROQ_API_KEY", "test-key"), \
             patch.object(ai, "GROQ_API_URL", "https://example.test"), \
             patch.object(ai, "GROQ_MODEL", "test-model"), \
             patch.object(ai.httpx, "AsyncClient", return_value=client_instance), \
             patch.object(ai.asyncio, "sleep", new=AsyncMock()):
            result = await ai._completion([{"role": "user", "content": "hi"}], max_tokens=1000)

        self.assertEqual(result, "ok")
        self.assertEqual(client_instance.post.await_count, 2)
        payload = client_instance.post.await_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], ai._MAX_TEXT_OUTPUT_TOKENS)


if __name__ == "__main__":
    unittest.main()
