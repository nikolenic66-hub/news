import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", ":memory:")

from app import storage


class PersistentActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = storage.DB_PATH
        self.old_history = storage.MAX_HISTORY
        storage.DB_PATH = os.path.join(self.temp.name, "test.sqlite3")
        storage.MAX_HISTORY = 1
        await storage.init_db()

    async def asyncTearDown(self):
        storage.DB_PATH = self.old_path
        storage.MAX_HISTORY = self.old_history
        self.temp.cleanup()

    async def test_activity_survives_message_history_pruning(self):
        for index in range(9):
            await storage.add_message(-100, 42, "player", "Игрок", "user", f"Сообщение {index}")
        stats = await storage.get_user_stats(-100, 42)
        self.assertEqual(stats["messages"], 9)
        top = await storage.get_top_users(-100)
        self.assertEqual(top[0][0], 42)
        self.assertEqual(top[0][3], 9)
        self.assertLessEqual(len(await storage.history(-100)), 3)
        import aiosqlite
        async with aiosqlite.connect(storage.DB_PATH) as db:
            rows = await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        tables = {row[0] for row in rows}
        self.assertNotIn("tournaments", tables)
        self.assertNotIn("tournament_entries", tables)
        self.assertNotIn("tournament_missed", tables)

    async def test_clear_chat_resets_activity(self):
        await storage.add_message(-100, 7, "p", "Игрок", "user", "Привет")
        await storage.clear_chat(-100)
        self.assertEqual((await storage.get_user_stats(-100, 7))["messages"], 0)


if __name__ == "__main__":
    unittest.main()
