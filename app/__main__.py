import asyncio,random,time,logging,sys,faulthandler
faulthandler.enable(file=sys.stderr, all_threads=True)
# If a dependency import stalls, emit its live Python stack every 10 seconds.
faulthandler.dump_traceback_later(10, repeat=True, file=sys.stderr)
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s: %(message)s',stream=sys.stdout,force=True)
log=logging.getLogger('fc-mate-startup')
log.info('Python entrypoint reached; imports are starting')
log.info('Import stage 1: aiogram')
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message
from aiogram.enums import ChatType
log.info('Import stage 2: configuration')
from .config import BOT_TOKEN,AI_KEY,BOT_NAME,PERSONA,ADMIN_IDS,REPLY_PROBABILITY
log.info('Import stage 3: storage')
from .storage import init_db,add_message,history,get_memory,save_memory,get_settings,set_setting,user_count,clear_chat,mark_missed,get_missed,find_user,remove_missed,update_reminder,get_missed_chats
log.info('Import stage 4: logic')
from .logic import is_fc_topic,is_direct_message,should_spontaneously_reply
log.info('Import stage 5: AI client')
from .ai import reply,summarize,ProviderError
log.info('All imports completed successfully')
log=logging.getLogger("fc-mate")
if not BOT_TOKEN:
 log.critical("Startup configuration error: TELEGRAM_BOT_TOKEN is missing")
 raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
if not AI_KEY:
 log.warning("AI key is missing: set AI_API_KEY or DEEPSEEK_API_KEY; AI replies will fail")
if __import__("os").getenv("DATABASE_URL"):
 log.warning("DATABASE_URL detected but this build uses SQLite; set DB_PATH to a persistent SQLite file if persistence is required")
bot=Bot(BOT_TOKEN);dp=Dispatcher()
last_spontaneous={};last_direct={};summary_counter={}
BOT_USERNAME=None
BOT_ID=None
TOURNAMENT_COOLDOWN=45*60
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
 await message.answer("/status — настройки чата\n/on, /off — включить или выключить меня (админы)\n/activity 0-50 — шанс моей инициативы (админы)\n/persona текст — мой характер (админы)\n/memory — долговременная память (админы)\n/forget — очистить только память (админы)\n/clear — очистить историю и память (админы)\n/missed — отметить прогульщика ответом\n/missed @username турнир — добавить в список\n/missedlist — список прогульщиков\n/played — снять с списка ответом или @username\n\nУпомяни меня или ответь на моё сообщение, чтобы вызвать меня напрямую.")
@dp.message(Command("missed"))
async def missed_command(message:Message):
 if not await is_admin(message):await message.reply("Турнирный список меняют администраторы.");return
 args=(message.text or "").split(maxsplit=1)
 target=message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else None
 tournament=args[1] if len(args)>1 else "текущий турнир"
 if target is None and len(args)>1:
  parts=args[1].split(maxsplit=1)
  if parts and parts[0].startswith("@"):
   row=await find_user(message.chat.id,parts[0][1:])
   if row:
    target_id,target_username,target_name=row
    tournament=parts[1] if len(parts)>1 else "текущий турнир"
    await mark_missed(message.chat.id,target_id,target_username,target_name,tournament)
    await message.reply(f"Добавил {target_name} в список прогульщиков турнира «{tournament}». Буду припоминать 😈");return
 if not target:await message.reply("Ответь на сообщение игрока: /missed название турнира, или /missed @username название турнира.");return
 await mark_missed(message.chat.id,target.id,target.username,target.full_name,tournament)
 await message.reply(f"Записал {target.full_name} как не сыгравшего «{tournament}». Буду периодически подкалывать и напоминать.")
@dp.message(Command("missedlist"))
async def missedlist_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы.");return
 rows=await get_missed(message.chat.id)
 if not rows:await message.reply("Список прогульщиков пуст.");return
 await message.reply("Список прогульщиков:\n"+"\n".join(f"• {name} — «{tour}»" for _,_,name,tour,_ in rows))
@dp.message(Command("played"))
async def played_command(message:Message):
 if not await is_admin(message):await message.reply("Только администраторы.");return
 args=(message.text or "").split(maxsplit=1)
 target=message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else None
 if target is None and len(args)>1 and args[1].startswith("@"):
  row=await find_user(message.chat.id,args[1][1:])
  if row:
   target_id,target_username,target_name=row
   target=type("Target",(),{"id":target_id,"full_name":target_name})()
 if not target:await message.reply("Ответь на сообщение игрока /played или напиши /played @username.");return
 removed=await remove_missed(message.chat.id,target.id)
 await message.reply("Снял с списка прогульщиков. Турнир сыгран! 🏆" if removed else "Его не было в списке.")
@dp.message(Command("status"))
async def status_command(message:Message):
 settings=await get_settings(message.chat.id);chance=REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
 await message.reply(f"FC Mate: {'активен' if settings['enabled'] else 'выключен'}\nИнициатива: {chance*100:.0f}%\nЗапомненных участников: {await user_count(message.chat.id)}\nПрогульщиков турнира: {len(await get_missed(message.chat.id))}")
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
 await message.reply("История, память, участники и список прогульщиков очищены; настройки сохранены.")
@dp.message(F.chat.type.in_({ChatType.GROUP,ChatType.SUPERGROUP}),F.text)
async def group_message(message:Message):
 user=message.from_user;text_in=(message.text or "").strip()
 if not user or user.is_bot or not text_in or text_in.startswith("/"):return
 now=time.time()
 name=user.full_name or user.username or "Игрок"
 await add_message(message.chat.id,user.id,user.username,name,"user",f"{name}: {text_in}")
 settings=await get_settings(message.chat.id)
 summary_counter[message.chat.id]=summary_counter.get(message.chat.id,0)+1
 if summary_counter[message.chat.id]>=60:
  try:
   old_memory=await get_memory(message.chat.id);update=await summarize(old_memory,await history(message.chat.id));await save_memory(message.chat.id,update)
  except Exception:log.exception("Memory summary refresh failed")
  summary_counter[message.chat.id]=0
 if not settings["enabled"]:return
 direct=is_direct_message(text_in,BOT_USERNAME,bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id==BOT_ID))
 if direct:
  if now-last_direct.get(message.chat.id,0)<12:return
  last_direct[message.chat.id]=now
 else:
  chance=REPLY_PROBABILITY if settings["activity"] is None else settings["activity"]
  elapsed=now-last_spontaneous.get(message.chat.id,0)
  if not should_spontaneously_reply(text_in,chance,random.random(),elapsed):return
 memory=await get_memory(message.chat.id);recent=await history(message.chat.id);prompt=[]
 if memory:prompt.append({"role":"system","content":"Память группы — используй ненавязчиво, не раскрывай её списком: "+memory})
 prompt.extend(recent)
 if direct:prompt.insert(0,{"role":"system","content":"Это прямое обращение или вопрос к тебе. Ответь по существу; не возвращай [SKIP], кроме если сообщение невозможно понять."})
 try:
  answer=await reply(prompt,settings["persona"] or PERSONA)
  if not answer:return
  await message.reply(answer[:4000]);await add_message(message.chat.id,None,None,BOT_NAME,"assistant",answer)
  if not direct:last_spontaneous[message.chat.id]=now
 except ProviderError as exc:
  log.warning("API issue: %s",exc)
  if direct:await message.reply("ИИ API не отвечает сейчас. Попробуй повторить чуть позже.")
 except Exception:
  log.exception("Unexpected group handler error")
  if direct:await message.reply("У меня техническая заминка, попробуй ещё раз.")

async def tournament_reminder_loop():
 while True:
  await asyncio.sleep(15*60)
  now=time.time()
  try:
   chats=await get_missed_chats()
  except Exception:
   log.exception("Could not load tournament reminder chats")
   continue
  for chat_id in chats:
   try:
    due=[row for row in await get_missed(chat_id) if now-row[4]>=TOURNAMENT_COOLDOWN]
    if not due:continue
    uid,username,display,tournament,last_rem=due[0]
    mention=f"@{username}" if username else display
    roast=f"{mention}, опять пропустил «{tournament}»? 😤 Турнир не пройдёт сам, даже если ты очень талантливо игнорируешь сетку. Залетай и закрывай долг!"
    await bot.send_message(chat_id,roast)
    await update_reminder(chat_id,uid,now)
   except Exception:
    log.exception("Tournament reminder failed for chat %s",chat_id)

async def main():
 global BOT_USERNAME,BOT_ID
 log.info("Startup: preparing SQLite")
 await init_db()
 log.info("Startup: SQLite is ready")
 log.info("Startup: validating Telegram token with getMe")
 me=await bot.get_me()
 BOT_USERNAME=me.username
 BOT_ID=me.id
 log.info("Startup: Telegram OK, username=@%s, id=%s",me.username,me.id)
 # Remove any stale webhook so long polling is not rejected by Telegram.
 await bot.delete_webhook(drop_pending_updates=False)
 log.info("Startup: webhook cleared; starting polling loop")
 asyncio.create_task(tournament_reminder_loop())
 await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())

if __name__=="__main__":
 try: asyncio.run(main())
 except Exception:
  log.exception("Process exited with fatal error")
  raise
