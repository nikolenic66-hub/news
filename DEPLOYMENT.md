# Deployment checklist: Neon + Telegram + DeepSeek + Amvera

This file contains setup instructions for the first live test. Do not put API keys, bot tokens, or database passwords in GitHub.

## 1. Create an isolated Neon project

1. Open Neon and create a separate project named `football-news`. Do not reuse the football-manager database URL.
2. Copy the connection string for the new database. Prefer the pooled connection string for an application worker.
3. In Amvera, configure it as `DATABASE_URL`. Include SSL in the connection string as recommended by Neon, for example `?sslmode=require`.
4. The app creates the initial `news_items` table during startup. Use a database/project owned by this bot only.

## 2. Create and configure a Telegram bot

1. Open BotFather in Telegram and create a bot.
2. Store the token in Amvera as `TELEGRAM_BOT_TOKEN`.
3. Add the bot to the target channel as an administrator with permission to post messages.
4. Set `TELEGRAM_CHANNEL_ID` to the channel's `@username` or numeric chat ID.
5. Check the bot and channel permissions with a manual test before turning on the worker.

## 3. Configure DeepSeek

1. Create an API key in the official DeepSeek platform.
2. Store it in Amvera as `DEEPSEEK_API_KEY`.
3. Set `DEEPSEEK_BASE_URL=https://api.deepseek.com`.
4. Set `DEEPSEEK_MODEL` to a model identifier enabled for the account. The example uses `deepseek-flash`; verify availability on the account before live launch.
5. Set a spending alert/limit in the provider account where available. The bot currently limits how many news items it sends to the editorial model in each cycle, but the provider account should also have budget monitoring.

## 4. Photo search

The first version searches Wikimedia Commons and only accepts clearly redistributable licenses (CC BY, CC BY-SA, CC0, and public-domain labels), omitting non-commercial licenses. It records the file page, license and author/credit. Attribution is included in the Telegram caption.

Set `WIKIMEDIA_USER_AGENT` to a truthful contact string, preferably with an email address you control. A generic Wikimedia photo is clearly labelled as illustrative. If no reusable photo can be found after the configured attempts, the item is not published.

Review Wikimedia Commons' current terms and each image's file page before production use. Automated license labels are an initial filter, not legal advice or a guarantee that every depicted person/event can be used for every commercial purpose.

## 5. Deploy from GitHub to Amvera

1. Create a new, separate Amvera project for the news bot.
2. Connect this repository: `nikolenic66-hub/news`.
3. Choose Dockerfile-based deployment. The repository includes a Dockerfile that starts `python -m app.main`.
4. Add environment variables in Amvera project settings using `.env.example` as a checklist. Add real secrets only in the Amvera settings UI.
5. Deploy and review logs. Expected startup includes `Football News Bot started`.
6. Test with a private/test channel first. The code begins publishing automatically when the required secrets are configured and licensed-image candidates are available.

## 6. Recommended first-run safeguards

Before pointing it at a public audience, start with a test channel and reduce activity:
- `MAX_POSTS_PER_DAY=2`
- `PUBLISH_INTERVAL_MINUTES=240`
- `PUBLISH_WINDOW_START_HOUR=9`
- `PUBLISH_WINDOW_END_HOUR=21`

Watch the logs for several cycles. Confirm source links, photo attribution, and text formatting. Then adjust to the planned maximum of 10 posts/day.

## 7. If the worker pauses

A send request can time out after Telegram may already have accepted the post. Such rows are marked `uncertain`, and automated publishing pauses until the channel is checked. This is deliberate to avoid duplicate posts. After confirming the message was not delivered, an administrator can update the row's status manually in the database; inspect the exact row first.

## 8. Secrets and privacy

- Never commit a populated `.env` file, tokens, database URLs, or API keys.
- The repository's `.gitignore` excludes `.env` files except `.env.example`.
- Rotate any token immediately if it is accidentally exposed.
- Repository visibility should be set to Private if you do not intend the source code to be public.
