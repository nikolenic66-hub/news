import os
from pathlib import Path

# Support legacy Amvera variable names and current FC Mate names.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AI_KEY = (os.getenv("AI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip()
AI_BASE_URL = (os.getenv("AI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
AI_MODEL = (os.getenv("AI_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
BOT_NAME = os.getenv("BOT_NAME", "FC Mate")
PERSONA = os.getenv("BOT_PERSONA", "Дружелюбный, смешной фанат FC Mobile, иногда язвительный, без токсичности.")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
try:
    REPLY_PROBABILITY = min(0.5, max(0.0, float(os.getenv("REPLY_PROBABILITY", "0.08"))))
except ValueError:
    REPLY_PROBABILITY = 0.08
try:
    MAX_HISTORY = min(30, max(6, int(os.getenv("MAX_HISTORY", "16"))))
except ValueError:
    MAX_HISTORY = 16

# This version uses SQLite; DATABASE_URL is detected in startup diagnostics but not consumed.
DB_PATH = os.getenv("DB_PATH", "data/chatmate.sqlite3").strip()
if DB_PATH != ":memory:":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
