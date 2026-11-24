# Васёк — AI companion for FC Mobile groups

Russian-speaking AI group participant. It discusses FC Mobile, cards/OVR, lineups, tactics and gameplay, remembers limited group context, and avoids noisy chatter.

## BotFather and Telegram
1. Create a bot with BotFather and save the token.
2. Add it to the target group.
3. In BotFather run `/setprivacy`, select your bot, set **Disable** so it can read normal group messages (privacy mode can take a few minutes; re-add bot if necessary).
4. You do not need to give it administrator privileges.

## Groq API
Create an API key in the [Groq Console](https://console.groq.com/keys). The default model is `openai/gpt-oss-120b`; the bot uses Groq's OpenAI-compatible Chat Completions endpoint.

The Groq Free Plan has per-model limits, including request and token-per-day limits. Check the current values for your organization in the Groq Console; free quotas can change. Image understanding uses the separate `GROQ_VISION_MODEL` (default `qwen/qwen3.8-27b`), so vision requests consume that model's quota and may have different pricing/limits.

## Deploy on Amvera
Build from this repository using Dockerfile. Set the environment variables below. Use persistent storage for the database path (e.g. mount storage and set `DB_PATH` to a file under that mount).

| Variable | Meaning |
|---|---|
| TELEGRAM_BOT_TOKEN | Required Telegram bot token |
| GROQ_API_KEY | Required Groq API key |
| GROQ_API_URL | Groq Chat Completions URL; defaults to `https://api.groq.com/openai/v1/chat/completions` |
| GROQ_MODEL | Text model name; defaults to `openai/gpt-oss-120b` |
| GROQ_VISION_MODEL | Vision model for image analysis; defaults to `qwen/qwen3.8-27b` |
| ADMIN_IDS | Optional comma-separated Telegram user IDs, in addition to Telegram group admins |
| BOT_PERSONA | Default personality |
| REPLY_PROBABILITY | Chance of unsolicited reply on relevant FC topic, default 0.08, capped at 0.50 |
| MAX_HISTORY | Recent context size, 6–30 messages |
| DB_PATH | SQLite file path, default /data/chatmate.sqlite3 (Amvera persistent data mount); DATABASE_URL is not used by this SQLite build |

## Commands in group
- `/help`, `/status`
- Admins: `/on`, `/off`, `/activity 0-50`, `/persona your style`, `/memory`, `/forget`, `/clear`
- Mention bot or reply to its message for a direct answer.

## Возможности Васька

- Анализ фотографий и скриншотов FC Mobile через Groq Vision: составы, карточки, OVR, позиции, задания и события. Для точного разбора в группе ответь на изображение или упомяни Васька в подписи.
- `/stats` и `/top` показывают накопительную статистику сообщений. Счётчики хранятся отдельно от короткой истории переписки и не обнуляются при её очистке для контекста.
- `/poll вопрос | вариант 1 | вариант 2` создаёт опрос Telegram; доступен администраторам группы.

## Memory and privacy
Stores recent group messages for context, cumulative activity counters, usernames, a short group memory and settings. Long-term summaries are limited to game-related preferences, recurring jokes and group context; sensitive information is excluded by prompt. `/forget` removes long-term summary, `/clear` removes stored messages, summary, participant list and activity counters. SQLite data persists only if Amvera storage is configured to persist the DB file. Do not put API secrets into GitHub.


## FC Mobile live monitoring

The built-in monitor checks recent promo-code publications 10 times per day (about every 2 hours 24 minutes) and refreshes FC Mobile news RSS every 15 minutes. Relevant player questions also trigger a question-specific Google News RSS lookup (rate-limited). It uses dated publications from the last 7 days as current context; if none are found, the bot is instructed not to recycle FIFA Mobile 2023/2024 knowledge as current FC Mobile facts. It ignores promo-code articles older than 48 hours or without a publication date to avoid reviving old codes. New codes are announced once in enabled groups where the bot has already received messages. Recent monitored articles and codes are supplied to Groq as context for relevant FC Mobile questions. Codes found in recent publications are labelled unverified; EA's redemption page is the final check. See [monitoring details](docs/FC_MOBILE_MONITORING.md).
