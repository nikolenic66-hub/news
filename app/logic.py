import re

BOT_NAME_CALL = re.compile(r"(?i)(?<![\w])(?:вас[её]к|васек|вась|васька)(?![\w])")

def is_bot_name_call(text:str)->bool:
 return bool(BOT_NAME_CALL.search(text or ""))

FC_WORDS=re.compile(r"(?i)(fc mobile|fcm|fcmobile|фк мобайл|фкм|овр|ovr|состав|карта игрока|карточк|обмен|ранг|дивизион|ивент|тактик|дриблинг|пак|квик селл|quick sell|рейтингов|гем|звезд|кампания)")
def is_fc_topic(text:str)->bool:return bool(FC_WORDS.search(text or ""))
def is_direct_message(text:str,bot_username:str|None,reply_to_bot:bool)->bool:
 return bool(bot_username and ("@"+bot_username.lower()) in (text or "").lower()) or reply_to_bot
def should_spontaneously_reply(text:str,activity:float,random_value:float,cooldown_elapsed:float,cooldown_seconds:float=240)->bool:
 return is_fc_topic(text) and cooldown_elapsed>=cooldown_seconds and random_value<max(0.0,min(.5,activity))


FOLLOWUP_START = re.compile(r"(?i)^(?:а\s+)?(?:почему|зачем|как|если|что|где|когда|сколько|какой|какая|какие|какое|и\s+что|и\s+как|а\s+дальше|дальше|понял|понятно|ясно|да|нет|неа|точно|серьёзно|серьезно|то\s+есть|это|он|она|они|там|тогда)\b")

def is_recent_bot_followup(text: str, previous_role: str | None, elapsed: float, window_seconds: float = 120) -> bool:
    """Recognize a short continuation immediately following the bot's reply."""
    value = (text or "").strip()
    if previous_role != "assistant" or elapsed < 0 or elapsed > window_seconds:
        return False
    if not value or len(value) > 140 or value.startswith("/"):
        return False
    return bool(FOLLOWUP_START.search(value))
