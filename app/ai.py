import httpx
from .config import AI_KEY, AI_BASE_URL, AI_MODEL
from .persona import SYSTEM_PROMPT

async def chat(messages, persona):
    if not AI_KEY:
        return 'У меня пока не подключён API-ключ ИИ. Админ, настрой AI_API_KEY.'
    payload={'model':AI_MODEL,'messages':[{'role':'system','content':SYSTEM_PROMPT.format(persona=persona)},*messages],'temperature':0.85,'max_tokens':550}
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.post(f'{AI_BASE_URL}/chat/completions',headers={'Authorization':f'Bearer {AI_KEY}'},json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()

async def summarize(memory, messages, persona):
    if not AI_KEY: return memory
    prompt='Обнови краткую долговременную память группы FC Mobile. Сохраняй устойчивые факты о людях, игровые предпочтения, постоянные шутки/мемы и важные договорённости. Не сохраняй случайные мелочи, приватные данные, догадки. Пиши компактно по-русски, максимум 1200 символов. Предыдущая память:\n'+(memory or '(пусто)')+'\nСвежий диалог:\n'+'\n'.join(f"{m['role']}: {m['content']}" for m in messages[-25:])
    payload={'model':AI_MODEL,'messages':[{'role':'system','content':'Ты аккуратный редактор памяти группового чата.'},{'role':'user','content':prompt}],'temperature':0.25,'max_tokens':500}
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.post(f'{AI_BASE_URL}/chat/completions',headers={'Authorization':f'Bearer {AI_KEY}'},json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()[:4000]
