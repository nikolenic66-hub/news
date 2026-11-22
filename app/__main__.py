import asyncio, random, time, logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ChatType
from .config import BOT_TOKEN, BOT_NAME, PERSONA, ADMIN_IDS, REPLY_PROBABILITY
from .storage import init_db, add_message, history, get_memory, save_memory
from .ai import chat, summarize

logging.basicConfig(level=logging.INFO)
log=logging.getLogger('fc-chatmate')
if not BOT_TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
bot=Bot(BOT_TOKEN)
dp=Dispatcher()
last_spontaneous={}
message_counts={}
activity=REPLY_PROBABILITY
persona=PERSONA

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(f'Я {BOT_NAME} — футбольный ИИ-собеседник FC Mobile. Добавьте меня в группу и отключите privacy mode через BotFather /setprivacy → Disable, чтобы я видел обычные сообщения.\n/help')

@dp.message(Command('help'))
async def help_cmd(m: Message):
    await m.answer('Команды:\n/activity — активность\n/activity 0-50 — настройка (админы)\n/persona текст — характер (админы)\n/memory — память группы (админы)\n/forget — очистить память (админы)')

@dp.message(Command('activity'))
async def activity_cmd(m: Message):
    global activity
    args=(m.text or '').split()
    if len(args)>1:
        if not m.from_user or m.from_user.id not in ADMIN_IDS:
            await m.reply('Настройку может менять администратор.'); return
        try: activity=max(0,min(50,int(args[1])))/100
        except ValueError: await m.reply('Укажи число от 0 до 50, например /activity 15'); return
        await m.reply(f'Спонтанность: {int(activity*100)}%')
    else: await m.reply(f'Сейчас {int(activity*100)}%. Упоминания и ответы мне имеют приоритет.')

@dp.message(Command('persona'))
async def persona_cmd(m: Message):
    global persona
    args=(m.text or '').split(maxsplit=1)
    if not m.from_user or m.from_user.id not in ADMIN_IDS:
        await m.reply('Доступ только администратору.'); return
    if len(args)<2:
        await m.reply('Текущий характер:\n'+persona+'\nИзменить: /persona веселый, язвительный фанат FC Mobile'); return
    persona=args[1][:500]
    await m.reply('Характер обновлён: '+persona)

@dp.message(Command('memory'))
async def memory_cmd(m: Message):
    if not m.from_user or m.from_user.id not in ADMIN_IDS:
        await m.reply('Доступ только администратору.'); return
    mem=await get_memory(m.chat.id)
    await m.reply(mem or 'Память пока пустая.')

@dp.message(Command('forget'))
async def forget_cmd(m: Message):
    if m.from_user and m.from_user.id in ADMIN_IDS:
        await save_memory(m.chat.id,'')
        await m.reply('Долговременная память группы очищена. История сообщений для контекста хранится отдельно.')
    else: await m.reply('Доступ только администратору.')

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def group_message(m: Message):
    if not m.from_user or m.from_user.is_bot or not m.text: return
    incoming=m.text.strip()
    if incoming.startswith('/'): return
    user=m.from_user
    display=user.full_name or user.username or 'Игрок'
    uname='@'+user.username if user.username else display
    await add_message(m.chat.id,user.id,user.username,display,'user',f'{display} ({uname}): {incoming}')
    me=await bot.get_me()
    direct=bool((me.username and f'@{me.username.lower()}' in incoming.lower()) or
                (m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id==me.id))
    now=time.monotonic()
    if not direct and (random.random()>=activity or now-last_spontaneous.get(m.chat.id,0)<90): return
    mem=await get_memory(m.chat.id)
    recent=await history(m.chat.id)
    messages=[]
    if mem: messages.append({'role':'system','content':'Память этой группы (используй ненавязчиво): '+mem})
    messages.extend(recent)
    try:
        answer=await chat(messages,persona)
        if answer:
            await m.reply(answer[:4000])
            await add_message(m.chat.id,None,None,BOT_NAME,'assistant',answer)
            last_spontaneous[m.chat.id]=now
            message_counts[m.chat.id]=message_counts.get(m.chat.id,0)+1
            if message_counts[m.chat.id]>=30:
                updated=await summarize(mem,recent,persona)
                if updated: await save_memory(m.chat.id,updated)
                message_counts[m.chat.id]=0
    except Exception:
        log.exception('AI provider call failed')
        if direct: await m.reply('ИИ API сейчас не отвечает. Попробуй чуть позже.')

async def main():
    await init_db()
    log.info('FC Mate polling start')
    await dp.start_polling(bot)

if __name__=='__main__':
    asyncio.run(main())
