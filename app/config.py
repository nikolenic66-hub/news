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
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_API_URL = os.getenv(
    "GROQ_API_URL",
    "https://api.groq.com/openai/v1/chat/completions",
).strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
BOT_NAME = "Васёк"
PERSONA = os.getenv(
    "BOT_PERSONA",
    "Дружелюбный, смешной фанат FC Mobile, иногда язвительный, без токсичности.",
)
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
REPLY_PROBABILITY = _float_env("REPLY_PROBABILITY", 0.08, 0.0, 0.5)
MAX_HISTORY = _int_env("MAX_HISTORY", 16, 6, 30)
DB_PATH = os.getenv("DB_PATH", "/data/chatmate.sqlite3").strip() or "/data/chatmate.sqlite3"
if DB_PATH != ":memory:":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
