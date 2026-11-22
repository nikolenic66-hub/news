import asyncio,random,time,logging
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message
from aiogram.enums import ChatType
from .config import BOT_TOKEN,BOT_NAME,PERSONA,ADMIN_IDS,REPLY_PROBABILITY
from .storage import init_db,add_message,history,get_memory,save_memory,get_settings,set_setting,user_count,clear_chat
from .logic import is_fc_topic,is_direct_message,should_spontaneously_reply
from .ai import reply,summarize,ProviderError

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("fc-mate")
if not BOT_TOKEN:raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
bot=Bot(BOT_TOKEN);dp=Dispatcher()
last_spontaneous={};last_direct={};summary_counter={}
async def is_admin(message:Message):
 if not message.from_user:return False
 if message.from_user.id in ADMIN_IDS:return True
 if message.chat.type not in (ChatType.GROUP,ChatType.SUPERGROUP):return False
 try:
  member=await bot.get_chat_member(message.chat.id,message.from_user.id)
  return member.status in ("administrator","creator")
 except Exception:return False

@dp.message(CommandStart())
async def start(message:Message):
 await message.answer(f"Я {BOT_NAME} — ИИ-игрок в чате FC Mobile. Обсуждаю карточки, составы, тактики, могу пошутить и иногда сам вклиниться в тему.\n/help")

@dp.message(Command("help"))
async def help_command(message:Message):
 await message.answer("/status — настройки чата\n/on, /off — включить или выключить меня (админы)\n/activity 0-50 — шанс моей инициативы (админы)\n/persona текст — мой характер (админы)\n/memory — долговременная память (админы)\n/forget — очистить только память (админы)\n/clear — очистить историю и память (админы)\n\nУпомяни меня или ответь на моё сообщение, чтобы вызвать меня напрямую.")

@dp.message(Command("status"))
async def status_command(message:Message):
 settings=await get_settings(message.chat.id);chance=REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
 await message.reply(f"FC Mate: {'активен' if settings['enabled'] else 'выключен'}\nИнициатива: {chance*100:.0f}%\nЗапомненных участников: {await user_count(message.chat.id)}")

@dp.message(Command("on"))
async def on_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы группы.");return
 await set_setting(message.chat.id,"enabled",True);await message.reply("Я снова в игре. 🟢")

@dp.message(Command("off"))
async def off_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы группы.");return
 await set_setting(message.chat.id,"enabled",False);await message.reply("Отключился. История сохранена.")

@dp.message(Command("activity"))
async def activity_command(message:Message):
 settings=await get_settings(message.chat.id);current=REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
 args=(message.text or "").split()
 if len(args)==1:await message.reply(f"Активность {current*100:.0f}%. Для изменения: /activity 0-50.");return
 if not await is_admin(message):await message.reply("Настройку меняют администраторы.");return
 try:value=max(0,min(50,int(args[1])))/100
 except ValueError:await message.reply("Введите целое число 0–50.");return
 await set_setting(message.chat.id,"activity",value);await message.reply(f"Вероятность инициативы теперь {value*100:.0f}%.")

@dp.message(Command("persona"))
async def persona_command(message:Message):
 settings=await get_settings(message.chat.id);args=(message.text or "").split(maxsplit=1)
 if len(args)==1:await message.reply("Текущий характер:\n"+(settings["persona"] or PERSONA));return
 if not await is_admin(message):await message.reply("Настройку меняют администраторы.");return
 await set_setting(message.chat.id,"persona",args[1]);await message.reply("Характер изменён.")

@dp.message(Command("memory"))
async def memory_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы.");return
 saved=await get_memory(message.chat.id);await message.reply(saved or "Память пока пустая.")

@dp.message(Command("forget"))
async def forget_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы.");return
 await save_memory(message.chat.id,"");await message.reply("Долговременная память очищена. История сообщений остаётся.")

@dp.message(Command("clear"))
async def clear_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы.");return
 await clear_chat(message.chat.id);summary_counter[message.chat.id]=0
 await message.reply("Вся сохранённая история, память и настройки этого чата удалены.")

@dp.message(F.chat.type.in_({ChatType.GROUP,ChatType.SUPERGROUP}),F.text)
async def group_message(message:Message):
 user=message.from_user
 text_in=(message.text or "").strip()
 if not user or user.is_bot or not text_in or text_in.startswith("/"):return
 name=user.full_name or user.username or "Игрок"
 await add_message(message.chat.id,user.id,user.username,name,"user",f"{name}: {text_in}")
 settings=await get_settings(message.chat.id)
 if not settings["enabled"]:return
 bot_user=await bot.get_me()
 direct=is_direct_message(text_in,bot_user.username,bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id==bot_user.id))
 now=time.monotonic()
 if direct:
  if now-last_direct.get(message.chat.id,0)<12:return
 else:
  chance=REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
  elapsed=now-last_spontaneous.get(message.chat.id,0)
  if not should_spontaneously_reply(text_in,chance,random.random(),elapsed):return
 memory=await get_memory(message.chat.id);recent=await history(message.chat.id)
 prompt=[]
 if memory:prompt.append({"role":"system","content":"Память группы — используй ненавязчиво, не раскрывай её списком: "+memory})
 prompt.extend(recent)
 try:
  answer=await reply(prompt,settings["persona"] or PERSONA)
  if not answer:return
  await message.reply(answer[:4000])
  await add_message(message.chat.id,None,None,BOT_NAME,"assistant",answer)
  if direct:last_direct[message.chat.id]=now
  else:last_spontaneous[message.chat.id]=now
  summary_counter[message.chat.id]=summary_counter.get(message.chat.id,0)+1
  if summary_counter[message.chat.id]>=40:
   updated=await summarize(memory,recent)
   await save_memory(message.chat.id,updated);summary_counter[message.chat.id]=0
 except ProviderError as exc:
  log.warning("API issue: %s",exc)
  if direct:await message.reply("ИИ API не отвечает сейчас. Попробуй повторить чуть позже.")
 except Exception:
  log.exception("Unexpected group handler error")
  if direct:await message.reply("У меня техническая заминка, попробуй ещё раз.")

async def main():
 await init_db()
 log.info("FC Mate is running")
 await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
if __name__=="__main__":asyncio.run(main())
