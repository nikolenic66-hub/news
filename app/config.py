import os

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
AI_KEY = os.getenv('AI_API_KEY', '').strip()
AI_BASE_URL = os.getenv('AI_BASE_URL', 'https://api.deepseek.com/v1').rstrip('/')
AI_MODEL = os.getenv('AI_MODEL', 'deepseek-chat')
BOT_NAME = os.getenv('BOT_NAME', 'FC Mate')
PERSONA = os.getenv('BOT_PERSONA', 'football friend, funny, confident, not obnoxious')
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
REPLY_PROBABILITY = min(1.0, max(0.0, float(os.getenv('REPLY_PROBABILITY', '0.18'))))
MAX_HISTORY = max(5, int(os.getenv('MAX_HISTORY', '18')))
DB_PATH = os.getenv('DB_PATH', 'chatmate.sqlite3')
