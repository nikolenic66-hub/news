# Amvera deploy notes

Build and run from the repository root with the included Dockerfile. The container starts `python -m app`.

Required environment variables:
- `TELEGRAM_BOT_TOKEN`: Telegram bot token from BotFather
- `APINEX_API_KEY`: Apinex API key
- `APINEX_API_URL`: full chat-completions URL; defaults to `https://api.apinex.bond/v1/chat/completions`
- `APINEX_MODEL`: model name; defaults to `free/deepseek-v4-pro-0813`

Optional settings:
- `BOT_NAME`: displayed bot name (default: FC Mate)
- `BOT_PERSONA`: bot personality prompt
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to change group settings
- `REPLY_PROBABILITY`: spontaneous group reply chance, from 0 to 0.5 (default: 0.08)
- `MAX_HISTORY`: number of recent messages kept in context (default: 16)
- `DB_PATH`: SQLite database file (default: `/data/chatmate.sqlite3`)

Important: this version uses SQLite via `aiosqlite`. It does not read `DATABASE_URL` and does not connect to PostgreSQL. Configure an Amvera persistent storage mount at `/data` if chat history and tournament lists must survive container rebuilds/restarts. The bot does not require `DEEPSEEK_MODEL`, `AI_API_KEY`, or `AI_BASE_URL`.

For group participation, add the bot to the group. To let it read ordinary group messages, disable privacy mode in BotFather with `/setprivacy` -> Disable. Group admin rights are not required for normal replies; the bot checks admin status for moderation commands.
