# Amvera deploy notes

Build and run from the repository root with the included Dockerfile. The container starts `python -m app`.

Required environment variables:
- `TELEGRAM_BOT_TOKEN`: Telegram bot token from BotFather
- `GROQ_API_KEY`: Groq API key from https://console.groq.com/keys
- `GROQ_API_URL`: Chat Completions URL; defaults to `https://api.groq.com/openai/v1/chat/completions`
- `GROQ_MODEL`: model name; defaults to `openai/gpt-oss-120b`

Optional settings:
- `BOT_NAME`: displayed bot name (default: FC Mate)
- `BOT_PERSONA`: bot personality prompt
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to change group settings
- `REPLY_PROBABILITY`: spontaneous group reply chance, from 0 to 0.5 (default: 0.08)
- `MAX_HISTORY`: number of recent messages kept in context (default: 16)
- `DB_PATH`: SQLite database file (default: `/data/chatmate.sqlite3`)

Important: this version uses SQLite via `aiosqlite`. It does not read `DATABASE_URL` and does not connect to PostgreSQL. Configure an Amvera persistent storage mount at `/data` if chat history and tournament lists must survive container rebuilds/restarts.

For group participation, add the bot to the group. To let it read ordinary group messages, disable privacy mode in BotFather with `/setprivacy` -> Disable. Group admin rights are not required for normal replies; the bot checks admin status for moderation commands.

HTTP request logging is reduced to WARNING so Telegram Bot API URLs containing the bot token are not written to application logs. Never put API secrets into GitHub.
