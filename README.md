# FC Mate — AI companion for FC Mobile groups

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
| BOT_NAME | Bot display name |
| BOT_PERSONA | Default personality |
| REPLY_PROBABILITY | Chance of unsolicited reply on relevant FC topic, default 0.08, capped at 0.50 |
| MAX_HISTORY | Recent context size, 6–30 messages |
| DB_PATH | SQLite file path, default /data/chatmate.sqlite3 (Amvera persistent data mount); DATABASE_URL is not used by this SQLite build |

## Commands in group
- `/help`, `/status`
- Admins: `/on`, `/off`, `/activity 0-50`, `/persona your style`, `/memory`, `/forget`, `/clear`
- Mention bot or reply to its message for a direct answer.

## FC Mate features\n\n- Telegram photo and image-document analysis through Groq Vision. Reply to a photo or mention the bot in its caption to request analysis; in groups, unaddressed images follow the configured low-noise activity chance. Images larger than 20 MB are rejected.\n- `/stats` and `/top` show message activity for the current chat.\n- `/tournament title`, `/join`, `/participants`, `/finish` provide simple registration management; only group admins can open/close registration.\n- `/poll question | option 1 | option 2` creates a Telegram poll; only group admins can create polls.\n\n## Memory and privacy
Stores recent group messages for context, usernames, a short group memory and settings. Long-term summaries are limited to game-related preferences, recurring jokes and group context; sensitive information is excluded by prompt. `/forget` removes long-term summary, `/clear` removes stored messages, summary and participant list. SQLite data persists only if Amvera storage is configured to persist the DB file. Do not put API secrets into GitHub.


## FC Mobile live monitoring

The built-in monitor checks public FC Mobile promo-code pages 10 times per day (about every 2 hours 24 minutes) and news RSS hourly and watches Google News RSS for EA updates, codes, player cards and gameplay/meta coverage. New codes are announced once in enabled groups where the bot has already received messages. Recent monitored articles and codes are supplied to Groq as context for relevant FC Mobile questions. Promo codes found on community sites are explicitly labelled unverified; EA's redemption page is the final check. See [monitoring details](docs/FC_MOBILE_MONITORING.md).
