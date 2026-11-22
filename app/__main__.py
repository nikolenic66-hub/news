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
activity=REPLY_PROBABILITY

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(f'Я {BOT_NAME} — футбольный ИИ-собеседник для вашей тусовки FC Mobile. Добавляйте меня в группу, включите разрешение читать сообщения (BotFather privacy mode), и я буду общаться, когда есть что сказать.\n/help')

@dp.message(Command('help'))
async def help_cmd(m: Message):
    await m.answer('Команды:\n/activity — посмотреть уровень моей инициативы\n/activity 0-50 — настройка активности (только админы)\n/memory — показать память группы (админы)\n/forget — очистить память группы (админы)\n/start — приветствие')

@dp.message(Command('activity'))
async def activity_cmd(m: Message):
    global activity
    args=(m.text or '').split()
    if len(args)>1:
        if m.from_user.id not in ADMIN_IDS:
            await m.reply('Эту настройку может менять администратор бота.')
            return
        try: activity=max(0,min(50,int(args[1])))/100
        except ValueError: await m.reply('Напиши число от 0 до 50, например /activity 15'); return
        await m.reply(f'Уровень спонтанности изменён: {int(activity*100)}% сообщений потенциально могут вызвать мою реакцию.')
    else: await m.reply(f'Сейчас {int(activity*100)}%. Реальный ответ зависит от контекста и паузы между моими сообщениями.')

@dp.message(Command('memory'))
async def memory_cmd(m: Message):
    if m.chat.type not in (ChatType.GROUP,ChatType.SUPERGROUP) or (m.from_user and m.from_user.id not in ADMIN_IDS):
        await m.reply('Доступно администраторам в группе.'); return
    mem=await get_memory(m.chat.id)
    await m.reply(mem or 'Память пока пустая.')

@dp.message(Command('forget'))
async def forget_cmd(m: Message):
    if m.from_user and m.from_user.id in ADMIN_IDS and m.chat.type in (ChatType.GROUP,ChatType.SUPERGROUP):
        await save_memory(m.chat.id,'')
        await m.reply('Память группы очищена. История сообщений в базе для контекста остаётся ограниченной.')
    else: await m.reply('Команда доступна администраторам группы.')

@dp.message(F.chat.type.in_({ChatType.GROUP,ChatType.SUPERGROUP}), F.text)async def group_message(m: Message):
    if not m.from_user or m.from_user.is_bot or not m.text: return
    text_in=m.text.strip()
    if text_in.startswith('/'): return
    name=m.from_user.full_name or m.from_user.username or 'Игрок'
    uname=f'@{m.from_user.username}' if m.from_user.username else name
    await add_message(m.chat.id,m.from_user.id,m.from_user.username,name,'user',f'{name} ({uname}): {text_in}')
    is_reply=(m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id== (await bot.get_me()).id)
    me=await bot.get_me()
    mentioned=bool(me.username and f'@{me.username.lower()}' in text_in.lower())
    now=time.monotonic()
    eligible=mentioned or bool(is_reply) or random.random()<activity
    if not eligible or now-last_spontaneous.get(m.chat.id,0)<65: return
    mem=await get_memory(m.chat.id)
    msgs=await history(m.chat.id)
    context=[]
    if mem: context.append({'role':'system','content':'Память о группе (используй деликатно, не перечисляй без повода): '+mem})
    context.extend(msgs)
    try:
        answer=await chat(context,PERSONA)
        if answer:
            await m.reply(answer[:4000])
            await add_message(m.chat.id,None,None,BOT_NAME,'assistant',answer)
            last_spontaneous[m.chat.id]=now
            if len(msgs)>0 and len(msgs)%30==0:
                new_mem=await summarize(mem,msgs,PERSONA)
                if new_mem: await save_memory(m.chat.id,new_mem)
    except Exception:
        log.exception('AI request failed')
        if mentioned or is_reply: await m.reply('Что-то API заглючил, повтори через минуту.')

async def main():
    await init_db()
    log.info('FC Mate bot starting polling')
    await dp.start_polling(bot)
if __name__=='__main__': asyncio.run(main())
