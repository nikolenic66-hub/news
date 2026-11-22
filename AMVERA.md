# Amvera deploy notes

Use Python runtime / Docker build from the repository root. The Dockerfile starts `python -m app`.

Environment variables:
- `TELEGRAM_BOT_TOKEN`: token from BotFather
- `AI_API_KEY`: key for compatible chat-completions API
- `AI_BASE_URL`: provider API base, defaults to DeepSeek-compatible endpoint
- `AI_MODEL`: model name
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to change bot settings
- `DB_PATH`: sqlite path (use an Amvera persistent storage mount if configured; otherwise database may be lost during redeploy)
- `REPLY_PROBABILITY`: default spontaneous participation chance (0.18)

For group participation, add bot to group and disable privacy mode with BotFather `/setprivacy` -> Disable. Avoid granting group admin rights unless needed. Do not commit secrets.
