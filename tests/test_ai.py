import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_PATH", ":memory:")

from app import ai


class VisionPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_is_attached_to_latest_user_message(self):
        messages = [
            {"role": "user", "content": "Игрок: привет"},
            {"role": "user", "content": "Игрок: Какой OVR у этой карты?"},
        ]
        with patch.object(ai, "_completion", new=AsyncMock(return_value="Не могу надёжно прочитать OVR.")) as completion:
            answer = await ai.reply(messages, "обычный стиль", image_data="ZmFrZQ==", image_mime="image/jpeg")

        self.assertIn("надёжно прочитать", answer)
        sent = completion.await_args.args[0]
        self.assertEqual(len([m for m in sent if m["role"] == "user"]), 2)
        latest = sent[-1]
        self.assertIsInstance(latest["content"], list)
        self.assertIn("Какой OVR", latest["content"][0]["text"])
        self.assertIn("не пиши типовое значение вроде 90", latest["content"][0]["text"])
        self.assertEqual(latest["content"][1]["type"], "image_url")
        self.assertEqual(completion.await_args.kwargs["model"], ai.GROQ_VISION_MODEL)

    async def test_image_is_added_as_user_turn_when_history_ends_with_assistant(self):
        messages = [
            {"role": "user", "content": "Игрок: привет"},
            {"role": "assistant", "content": "Привет!"},
        ]
        with patch.object(ai, "_completion", new=AsyncMock(return_value="Скриншот вижу.")) as completion:
            await ai.reply(messages, "обычный стиль", image_data="ZmFrZQ==")

        sent = completion.await_args.args[0]
        self.assertEqual(sent[-1]["role"], "user")
        self.assertEqual(sent[-1]["content"][1]["type"], "image_url")


if __name__ == "__main__":
    unittest.main()
