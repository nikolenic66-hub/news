import os
from pathlib import Path

def _float_env(name, default, low, high):
    try:
        return min(high, max(low, float(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default

def _int_env(name, default, low, high):
    try:
        return min(high, max(low, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
# Match the proven Manager2 provider configuration exactly.
APINEX_API_KEY = os.getenv("APINEX_API_KEY", "").strip()
APINEX_API_URL = os.getenv("APINEX_API_URL", "https://api.apinex.bond/v1/chat/completions").strip()
APINEX_MODEL = os.getenv("APINEX_MODEL", "free/deepseek-v4-pro-0813").strip()
BOT_NAME = os.getenv("BOT_NAME", "FC Mate").strip() or "FC Mate"
PERSONA = os.getenv("BOT_PERSONA", "Дружелюбный, смешной фанат FC Mobile, иногда язвительный, без токсичности.")
ADMIN_IDS = {int(value.strip()) for value in os.getenv("ADMIN_IDS", "").split(",") if value.strip().isdigit()}
REPLY_PROBABILITY = _float_env("REPLY_PROBABILITY", 0.08, 0.0, 0.5)
MAX_HISTORY = _int_env("MAX_HISTORY", 16, 6, 30)
DB_PATH = os.getenv("DB_PATH", "/data/chatmate.sqlite3").strip() or "/data/chatmate.sqlite3"
if DB_PATH != ":memory:":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
