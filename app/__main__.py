import asyncio
import base64
import logging
import mimetypes
import random
import time

import httpx

from .config import BOT_TOKEN, GROQ_API_KEY, GROQ_API_URL, GROQ_MODEL, GROQ_VISION_MODEL, BOT_NAME, PERSONA, ADMIN_IDS, REPLY_PROBABILITY
from .storage import (
    init_db, add_message, history, get_memory, save_memory, get_settings,
    set_setting, user_count, clear_chat, get_enabled_group_chats,
    get_user_stats, get_top_users, get_recent_intel,
)
from .logic import is_fc_topic
from .ai import reply, summarize, ProviderError
from .monitor import monitor_loop, build_intel_context, format_news_digest, format_sources_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Telegram bot tokens are embedded in Bot API URL paths. Never log httpx
# request URLs, otherwise the token is exposed in Amvera application logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = logging.getLogger("vasek")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
HTTP = None
BOT_ID = None
BOT_USERNAME = None
last_spontaneous = {}
last_direct = {}
summary_counter = {}

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


async def broadcast_promo_alert(message):
    try:
        chats = await get_enabled_group_chats()
    except Exception:
        log.exception("Could not load groups for promo-code alert")
        return
    for chat_id in chats:
        try:
            await send(chat_id, message)
        except Exception:
            log.exception("Could not send promo-code alert to chat %s", chat_id)


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
    for entity in (message.get("entities") or []) + (message.get("caption_entities") or []):
        if entity.get("type") == "mention":
            offset, length = entity.get("offset", 0), entity.get("length", 0)
            if text[offset:offset + length].lower() == needle:
                return True
    return False


async def handle_command(message, command, args):
    chat_id = message["chat"]["id"]
    group_admin_commands = {
        "on", "off", "activity", "persona", "memory", "forget", "clear",
        "poll",
    }
    if message.get("chat", {}).get("type") == "private" and command in group_admin_commands:
        await send(
            chat_id,
            "Эта команда меняет настройки группы. Отправь её прямо в чате FC Mobile — там я проверю твои права администратора. Здесь можешь просто общаться со мной.",
            message.get("message_id"),
        )
        return

    if command == "start":
        await send(chat_id, f"Я {BOT_NAME} — свой человек в чате FC Mobile. Обсуждаю карточки, составы и тактики, могу пошутить и иногда сам вклиниться в тему.\n/help", message.get("message_id"))
    elif command == "help":
        await send(chat_id, "/status — настройки чата\n/on, /off — включить или выключить меня (админы)\n/activity 0-50 — шанс моей инициативы (админы)\n/persona текст — мой характер (админы)\n/memory — долговременная память (админы)\n/forget — очистить только память (админы)\n/clear — очистить историю и память (админы)\n/stats — твоя статистика в чате\n/top — рейтинг активности\n/news — свежие новости FC Mobile\n/sources — источники и время обновления\n/poll вопрос | вариант 1 | вариант 2 — опрос (админ)\n\nУпомяни меня или ответь на моё сообщение, чтобы вызвать меня напрямую.", message.get("message_id"))
    elif command == "news":
        answer = format_news_digest(await get_recent_intel(20), limit=6)
        await send(chat_id, "📰 Новости FC Mobile\n\n" + answer, message.get("message_id"))
    elif command == "sources":
        answer = format_sources_status(await get_recent_intel(20), limit=8)
        await send(chat_id, "🔎 Источники Васька\n\n" + answer, message.get("message_id"))
    elif command == "stats":
        stats = await get_user_stats(chat_id, user.get("id"))
        await send(chat_id, f"Твоя статистика в этом чате: сообщений — {stats['messages']}. Последняя активность: {stats['last_seen'] or 'пока нет данных'}.", message.get("message_id"))
    elif command == "top":
        rows = await get_top_users(chat_id, 10)
        if not rows:
            answer = "Пока статистики нет."
        else:
            answer = "🏆 Актив чата по сообщениям:\n" + "\n".join(f"{i}. {row[1] or 'Игрок'} — {row[3]}" for i, row in enumerate(rows, 1))
        await send(chat_id, answer, message.get("message_id"))
    elif command == "poll":
        if not await is_admin(message):
            await send(chat_id, "Создавать опросы могут администраторы.", message.get("message_id")); return
        parts = [part.strip() for part in args.split("|")]
        if len(parts) < 3 or not parts[0] or any(not p for p in parts[1:]) or len(parts) > 11:
            await send(chat_id, "Формат: /poll За кого болеем? | Реал | Барса (от 2 до 10 вариантов).", message.get("message_id")); return
        await telegram("sendPoll", chat_id=chat_id, question=parts[0][:300], options=parts[1:], is_anonymous=False, allows_multiple_answers=False)
    elif command == "status":
        settings = await get_settings(chat_id)
        chance = REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
        await send(chat_id, f"{BOT_NAME}: {'активен' if settings['enabled'] else 'выключен'}\nИнициатива: {chance*100:.0f}%\nЗапомненных участников: {await user_count(chat_id)}", message.get("message_id"))
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
            answer = "История, память, участники и статистика активности очищены; настройки сохранены."
        await send(chat_id, answer, message.get("message_id"))



async def download_message_image(message):
    """Download a Telegram photo/image document and encode it for Groq Vision."""
    photos = message.get("photo") or []
    document = message.get("document") or {}
    if photos:
        file_id = photos[-1].get("file_id")
        mime = "image/jpeg"
        size = photos[-1].get("file_size", 0)
    elif document.get("mime_type", "").startswith("image/"):
        file_id = document.get("file_id")
        mime = document.get("mime_type") or mimetypes.guess_type(document.get("file_name", ""))[0] or "image/jpeg"
        size = document.get("file_size", 0)
    else:
        return None
    if not file_id:
        return None
    if size and size > 20 * 1024 * 1024:
        raise ValueError("Изображение больше лимита 20 МБ.")
    meta = await telegram("getFile", file_id=file_id)
    path = meta.get("file_path")
    if not path:
        raise ValueError("Telegram не вернул путь к изображению.")
    response = await HTTP.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
    response.raise_for_status()
    if len(response.content) > 20 * 1024 * 1024:
        raise ValueError("Изображение больше лимита 20 МБ.")
    return {"data": base64.b64encode(response.content).decode("ascii"), "mime": mime}


async def handle_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text_in = (message.get("text") or message.get("caption") or "").strip()
    user = message.get("from") or {}
    has_image = bool(message.get("photo")) or (
        (message.get("document") or {}).get("mime_type", "").startswith("image/")
    )
    if not chat_id or (not text_in and not has_image) or user.get("is_bot") or not user.get("id"):
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

    stored_text = text_in or ("[Отправлено изображение]" if has_image else "")
    await add_message(chat_id, user["id"], user.get("username"), name, "user", f"{name}: {stored_text}")
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
        # Images in an FC Mobile group are eligible for the same low-noise
        # initiative chance; direct replies always get full image analysis.
        eligible = has_image or is_fc_topic(text_in)
        if not eligible or elapsed < 240 or random.random() >= chance:
            return

    image_data = None
    if has_image:
        try:
            image_data = await download_message_image(message)
        except Exception as exc:
            log.warning("Telegram image download failed: %s", exc)
            if direct:
                await send(chat_id, f"Не получилось открыть изображение: {exc}", message.get("message_id"))
            return

    memory = await get_memory(chat_id)
    prompt = []
    if memory:
        prompt.append({"role": "system", "content": "Память группы — используй ненавязчиво, не раскрывай её списком: " + memory})
    prompt.extend(await history(chat_id))
    intel_context = await build_intel_context(text_in or ("FC Mobile: анализ изображения" if has_image else ""), HTTP)
    if intel_context:
        prompt.insert(0, {"role": "system", "content": intel_context})
    if direct:
        prompt.insert(0, {"role": "system", "content": "Это прямое обращение или вопрос к тебе. Ответь по существу; не возвращай [SKIP], кроме если сообщение невозможно понять."})
    try:
        answer = await reply(
            prompt,
            settings["persona"] or PERSONA,
            image_data=image_data["data"] if image_data else None,
            image_mime=image_data["mime"] if image_data else "image/jpeg",
        )
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


async def main():
    global HTTP, BOT_ID, BOT_USERNAME
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not GROQ_API_KEY:
        log.error("GROQ_API_KEY is missing; AI replies are disabled")
    log.info(
        "AI config: provider=Groq base_url=%s model=%s key_configured=%s",
        GROQ_API_URL,
        GROQ_MODEL,
        bool(GROQ_API_KEY),
    )
    HTTP = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15))
    try:
        log.info("Startup: initializing SQLite")
        await init_db()
        me = await telegram("getMe")
        BOT_ID, BOT_USERNAME = me["id"], me.get("username")
        try:
            await telegram("setMyName", name=BOT_NAME)
        except Exception:
            log.warning("Could not update Telegram profile name automatically")
        log.info("Telegram API connected as @%s (id=%s)", BOT_USERNAME, BOT_ID)
        await telegram("deleteWebhook", drop_pending_updates=False)
        asyncio.create_task(monitor_loop(HTTP, broadcast_promo_alert))
        offset = None
        log.info("Васёк started; polling updates")
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
