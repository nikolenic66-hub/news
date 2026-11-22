import httpx
from .config import AI_KEY,AI_BASE_URL,AI_MODEL
from .persona import SYSTEM_PROMPT

class ProviderError(RuntimeError): pass

async def _completion(messages,temperature=0.8,max_tokens=450):
    if not AI_KEY: raise ProviderError("AI_API_KEY не настроен")
    if not AI_MODEL: raise ProviderError("AI_MODEL пуст")
    payload={"model":AI_MODEL,"messages":messages,"temperature":temperature,"max_tokens":max_tokens}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40,connect=10)) as client:
            response=await client.post(f"{AI_BASE_URL}/chat/completions",
              headers={"Authorization":f"Bearer {AI_KEY}","Content-Type":"application/json"},json=payload)
            response.raise_for_status()
            data=response.json()
        answer=data["choices"][0]["message"]["content"]
        if not isinstance(answer,str) or not answer.strip(): raise ProviderError("Пустой ответ модели")
        return answer.strip()
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        raise ProviderError(f"Провайдер не ответил корректно: {exc}") from exc

async def reply(messages,persona):
    system=SYSTEM_PROMPT.format(persona=persona or "стандартный FC Mate")
    answer=await _completion([{"role":"system","content":system},*messages],temperature=.85,max_tokens=500)
    if answer.strip().upper()=="[SKIP]": return ""
    return answer[:4000]

async def summarize(memory,messages):
    if not messages: return memory or ""
    prompt=("Сделай краткое обновление долгосрочной памяти этой игровой группы. "
      "Сохраняй только устойчивые, не чувствительные факты: игровые предпочтения, любимые клубы/карты, "
      "общие мемы и важные контексты. Не сохраняй адреса, контакты, здоровье, финансы, личные секреты, "
      "не делай догадок. Русский язык, максимум 1000 символов. Предыдущая память:\n"+(memory or "пусто")+
      "\nСвежие сообщения:\n"+"\n".join(m["content"] for m in messages[-30:]))
    result=await _completion([{"role":"system","content":"Редактор безопасной памяти группового чата."},{"role":"user","content":prompt}],temperature=.2,max_tokens=400)
    return result[:3000]
