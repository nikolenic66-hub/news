import asyncio
import logging
import random
import time

import httpx

from .config import BOT_TOKEN, AI_KEY, BOT_NAME, PERSONA, ADMIN_IDS, REPLY_PROBABILITY
from .storage import (
    init_db, add_message, history, get_memory, save_memory, get_settings,
    set_setting, user_count, clear_chat, mark_missed, get_missed,
    find_user, remove_missed, update_reminder, get_missed_chats,
)
from .logic import is_fc_topic, is_direct_message, should_spontaneously_reply
from .ai import reply, summarize, ProviderError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fc-mate")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
HTTP = None
BOT_ID = None
BOT_USERNAME = None
last_spontaneous = {}
last_direct = {}
summary_counter = {}
TOURNAMENT_COOLDOWN = 45 * 60


class TelegramAPIError(RuntimeError):
    pass


async def telegram(method, **payload):
    response = await HTTP.post(f"{API}/{method}", json=payload)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise TelegramAPIError(data.get("description", "Telegram API error"))
    return data.get("result")


async def send(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": str(text)[:4000]}
    if reply_to is not None:
        payload["reply_parameters"] = {"message_id": reply_to}
    return await telegram("sendMessage", **payload)


async def is_admin(message):
    user = message.get("from") or {}
    uid = user.get("id")
    if uid in ADMIN_IDS:
        return True
    chat = message.get("chat") or {}
    if chat.get("type") not in ("group", "supergroup") or not uid:
        return False
    try:
        member = await telegram("getChatMember", chat_id=chat["id"], user_id=uid)
        return member.get("status") in ("administrator", "creator")
    except Exception:
        log.exception("Could not verify group administrator")
        return False


def user_name(user):
    return (user.get("first_name", "") + " " + user.get("last_name", "")).strip() or user.get("username") or "Игрок"


def message_is_reply_to_bot(message):
    replied = message.get("reply_to_message") or {}
    return (replied.get("from") or {}).get("id") == BOT_ID


def message_mentions_bot(message, text):
    if not BOT_USERNAME:
        return False
    needle = "@" + BOT_USERNAME.lower()
    if needle in text.lower():
        return True
    for entity in message.get("entities") or []:
        if entity.get("type") == "mention":
            offset, length = entity.get("offset", 0), entity.get("length", 0)
            if text[offset:offset + length].lower() == needle:
                return True
    return False


async def handle_command(message, command, args):
    chat_id = message["chat"]["id"]
    reply_message = message.get("reply_to_message") or {}
    target = reply_message.get("from") or None

    # Group settings and tournament administration must be changed in the
    # group itself, where Telegram lets us verify the sender's admin status.
    group_admin_commands = {
        "on", "off", "activity", "persona", "memory", "forget", "clear",
        "missed", "missedlist", "played",
    }
    if message.get("chat", {}).get("type") == "private" and command in group_admin_commands:
        await send(
            chat_id,
            "Эта команда меняет настройки группы. Отправь её прямо в чате FC Mobile — там я проверю твои права администратора. Здесь можешь просто общаться со мной.",
            message.get("message_id"),
        )
        return

    if command == "start":
        await send(chat_id, f"Я {BOT_NAME} — ИИ-игрок в чате FC Mobile. Обсуждаю карточки, составы и тактики, могу пошутить и иногда сам вклиниться в тему.\n/help", message.get("message_id"))
    elif command == "help":
        await send(chat_id, "/status — настройки чата\n/on, /off — включить или выключить меня (админы)\n/activity 0-50 — шанс моей инициативы (админы)\n/persona текст — мой характер (админы)\n/memory — долговременная память (админы)\n/forget — очистить только память (админы)\n/clear — очистить историю и память (админы)\n/missed — отметить прогульщика ответом\n/missed @username турнир — добавить в список\n/missedlist — список прогульщиков\n/played — снять с списка ответом или @username\n\nУпомяни меня или ответь на моё сообщение, чтобы вызвать меня напрямую.", message.get("message_id"))
    elif command == "missed":
        if not await is_admin(message):
            await send(chat_id, "Турнирный список меняют администраторы.", message.get("message_id")); return
        tournament = args or "текущий турнир"
        if target is None and args.startswith("@"):
            parts = args.split(maxsplit=1)
            row = await find_user(chat_id, parts[0][1:])
            if row:
                tournament = parts[1] if len(parts) > 1 else "текущий турнир"
                await mark_missed(chat_id, row[0], row[1], row[2], tournament)
                await send(chat_id, f"Добавил {row[2]} в список прогульщиков турнира «{tournament}». Буду припоминать 😈", message.get("message_id")); return
        if not target:
            await send(chat_id, "Ответь на сообщение игрока: /missed название турнира, или /missed @username название турнира.", message.get("message_id")); return
        await mark_missed(chat_id, target["id"], target.get("username"), user_name(target), tournament)
        await send(chat_id, f"Записал {user_name(target)} как не сыгравшего «{tournament}». Буду периодически подкалывать и напоминать.", message.get("message_id"))
    elif command == "missedlist":
        if not await is_admin(message):
            await send(chat_id, "Только администраторы.", message.get("message_id")); return
        rows = await get_missed(chat_id)
        await send(chat_id, "Список прогульщиков:\n" + "\n".join(f"• {name} — «{tour}»" for _, _, name, tour, _ in rows) if rows else "Список прогульщиков пуст.", message.get("message_id"))
    elif command == "played":
        if not await is_admin(message):
            await send(chat_id, "Только администраторы.", message.get("message_id")); return
        if target is None and args.startswith("@"):
            row = await find_user(chat_id, args.split()[0][1:])
            if row:
                target = {"id": row[0], "first_name": row[2]}
        if not target:
            await send(chat_id, "Ответь на сообщение игрока /played или напиши /played @username.", message.get("message_id")); return
        removed = await remove_missed(chat_id, target["id"])
        await send(chat_id, "Снял с списка прогульщиков. Турнир сыгран! 🏆" if removed else "Его не было в списке.", message.get("message_id"))
    elif command == "status":
        settings = await get_settings(chat_id)
        chance = REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
        await send(chat_id, f"FC Mate: {'активен' if settings['enabled'] else 'выключен'}\nИнициатива: {chance*100:.0f}%\nЗапомненных участников: {await user_count(chat_id)}\nПрогульщиков турнира: {len(await get_missed(chat_id))}", message.get("message_id"))
    elif command in ("on", "off"):
        if not await is_admin(message):
            await send(chat_id, "Только администраторы группы.", message.get("message_id")); return
        enabled = command == "on"
        await set_setting(chat_id, "enabled", enabled)
        await send(chat_id, "Я снова в игре. 🟢" if enabled else "Отключился. История сохранена.", message.get("message_id"))
    elif command == "activity":
        settings = await get_settings(chat_id)
        current = REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
        if not args:
            await send(chat_id, f"Активность {current*100:.0f}%. Для изменения: /activity 0-50.", message.get("message_id")); return
        if not await is_admin(message):
            await send(chat_id, "Настройку меняют администраторы.", message.get("message_id")); return
        try:
            value = max(0, min(50, int(args.split()[0]))) / 100
        except ValueError:
            await send(chat_id, "Введите целое число 0–50.", message.get("message_id")); return
        await set_setting(chat_id, "activity", value)
        await send(chat_id, f"Вероятность инициативы теперь {value*100:.0f}%.", message.get("message_id"))
    elif command == "persona":
        settings = await get_settings(chat_id)
        if not args:
            await send(chat_id, "Текущий характер:\n" + (settings["persona"] or PERSONA), message.get("message_id")); return
        if not await is_admin(message):
            await send(chat_id, "Настройку меняют администраторы.", message.get("message_id")); return
        await set_setting(chat_id, "persona", args)
        await send(chat_id, "Характер изменён.", message.get("message_id"))
    elif command == "memory":
        if not await is_admin(message):
            await send(chat_id, "Только администраторы.", message.get("message_id")); return
        await send(chat_id, await get_memory(chat_id) or "Память пока пустая.", message.get("message_id"))
    elif command in ("forget", "clear"):
        if not await is_admin(message):
            await send(chat_id, "Только администраторы.", message.get("message_id")); return
        if command == "forget":
            await save_memory(chat_id, "")
            answer = "Долговременная память очищена. История сообщений остаётся."
        else:
            await clear_chat(chat_id)
            summary_counter[chat_id] = 0
            answer = "История, память, участники и список прогульщиков очищены; настройки сохранены."
        await send(chat_id, answer, message.get("message_id"))


async def handle_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text_in = (message.get("text") or "").strip()
    user = message.get("from") or {}
    if not chat_id or not text_in or user.get("is_bot") or not user.get("id"):
        return
    if text_in.startswith("/"):
        first, _, args = text_in.partition(" ")
        command = first[1:].split("@", 1)[0].lower()
        if "@" in first and first.split("@", 1)[1].lower() != (BOT_USERNAME or "").lower():
            return
        await handle_command(message, command, args.strip())
        return
    name = user_name(user)
    is_private = chat.get("type") == "private"
    if not is_private and chat.get("type") not in ("group", "supergroup"):
        return

    # Private chat is always a direct conversation. In groups, keep the
    # existing mention/reply trigger and low-frequency spontaneous behavior.
    await add_message(chat_id, user["id"], user.get("username"), name, "user", f"{name}: {text_in}")
    summary_counter[chat_id] = summary_counter.get(chat_id, 0) + 1
    if summary_counter[chat_id] >= 60:
        try:
            old_memory = await get_memory(chat_id)
            update = await summarize(old_memory, await history(chat_id))
            await save_memory(chat_id, update)
        except Exception:
            log.exception("Memory summary refresh failed")
        summary_counter[chat_id] = 0

    settings = await get_settings(chat_id)
    if not settings["enabled"]:
        return
    direct = is_private or message_mentions_bot(message, text_in) or message_is_reply_to_bot(message)
    now = time.time()
    if direct and not is_private:
        if now - last_direct.get(chat_id, 0) < 12:
            return
        last_direct[chat_id] = now
    elif not is_private:
        chance = REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
        elapsed = now - last_spontaneous.get(chat_id, 0)
        if not should_spontaneously_reply(text_in, chance, random.random(), elapsed):
            return

    memory = await get_memory(chat_id)
    prompt = []
    if memory:
        prompt.append({"role": "system", "content": "Память группы — используй ненавязчиво, не раскрывай её списком: " + memory})
    prompt.extend(await history(chat_id))
    if direct:
        prompt.insert(0, {"role": "system", "content": "Это прямое обращение или вопрос к тебе. Ответь по существу; не возвращай [SKIP], кроме если сообщение невозможно понять."})
    try:
        answer = await reply(prompt, settings["persona"] or PERSONA)
        if answer:
            await send(chat_id, answer, message.get("message_id"))
            await add_message(chat_id, None, None, BOT_NAME, "assistant", answer)
            if not direct:
                last_spontaneous[chat_id] = now
    except ProviderError as exc:
        log.warning("AI provider issue: %s", exc)
        if direct:
            await send(chat_id, "ИИ API не отвечает сейчас. Попробуй повторить чуть позже.", message.get("message_id"))
    except Exception:
        log.exception("Unexpected group handler error")
        if direct:
            await send(chat_id, "У меня техническая заминка, попробуй ещё раз.", message.get("message_id"))


async def tournament_reminder_loop():
    while True:
        await asyncio.sleep(15 * 60)
        now = time.time()
        try:
            chats = await get_missed_chats()
        except Exception:
            log.exception("Could not load tournament reminder chats")
            continue
        for chat_id in chats:
            try:
                due = [row for row in await get_missed(chat_id) if now - row[4] >= TOURNAMENT_COOLDOWN]
                if not due:
                    continue
                uid, username, display, tournament, _ = due[0]
                mention = f"@{username}" if username else display
                roast = f"{mention}, опять пропустил «{tournament}»? 😤 Турнир не пройдёт сам, даже если ты очень талантливо игнорируешь сетку. Залетай и закрывай долг!"
                await send(chat_id, roast)
                await update_reminder(chat_id, uid, now)
            except Exception:
                log.exception("Tournament reminder failed for chat %s", chat_id)


async def main():
    global HTTP, BOT_ID, BOT_USERNAME
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not AI_KEY:
        log.error("APINEX_API_KEY is missing; AI replies are disabled")
    log.info(
        "AI config: provider=APInex base_url=%s model=%s key_configured=%s",
        __import__("app.config", fromlist=["AI_BASE_URL"]).AI_BASE_URL,
        __import__("app.config", fromlist=["AI_MODEL"]).AI_MODEL,
        bool(AI_KEY),
    )
    HTTP = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15))
    try:
        log.info("Startup: initializing SQLite")
        await init_db()
        me = await telegram("getMe")
        BOT_ID, BOT_USERNAME = me["id"], me.get("username")
        log.info("Telegram API connected as @%s (id=%s)", BOT_USERNAME, BOT_ID)
        await telegram("deleteWebhook", drop_pending_updates=False)
        asyncio.create_task(tournament_reminder_loop())
        offset = None
        log.info("FC Mate started; polling updates")
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                updates = await telegram("getUpdates", **params)
                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if message:
                        try:
                            await handle_message(message)
                        except Exception:
                            log.exception("Update handler failed (update_id=%s)", update["update_id"])
            except (httpx.HTTPError, TelegramAPIError, ValueError) as exc:
                log.warning("Telegram polling error: %s", exc)
                await asyncio.sleep(3)
    finally:
        await HTTP.aclose()


if __name__ == "__main__":
    asyncio.run(main())
