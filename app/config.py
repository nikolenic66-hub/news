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

# Apinex is the single AI provider. Keep the environment names aligned
# with the Amvera variables used by this deployment.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AI_KEY = os.getenv("APINEX_API_KEY", "").strip()
AI_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.apinex.bond/v1").strip().rstrip("/")
AI_MODEL = os.getenv("DEEPSEEK_MODEL", "free/deepseek-v4-pro-0813").strip()
BOT_NAME = os.getenv("BOT_NAME", "FC Mate").strip() or "FC Mate"
PERSONA = os.getenv("BOT_PERSONA", "Дружелюбный, смешной фанат FC Mobile, иногда язвительный, без токсичности.")
ADMIN_IDS = {int(value.strip()) for value in os.getenv("ADMIN_IDS", "").split(",") if value.strip().isdigit()}
REPLY_PROBABILITY = _float_env("REPLY_PROBABILITY", 0.08, 0.0, 0.5)
MAX_HISTORY = _int_env("MAX_HISTORY", 16, 6, 30)

# SQLite path: use Amvera's persistent /data mount unless explicitly overridden.
DB_PATH = os.getenv("DB_PATH", "/data/chatmate.sqlite3").strip() or "/data/chatmate.sqlite3"
if DB_PATH != ":memory:":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
