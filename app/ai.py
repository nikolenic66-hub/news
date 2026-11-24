import httpx

from .config import GROQ_API_KEY, GROQ_API_URL, GROQ_MODEL
from .persona import SYSTEM_PROMPT


class ProviderError(RuntimeError):
    pass


async def _completion(messages, temperature=0.8, max_tokens=450):
    if not GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY не настроен в Amvera")
    if not GROQ_API_URL:
        raise ProviderError("GROQ_API_URL не настроен")
    if not GROQ_MODEL:
        raise ProviderError("GROQ_MODEL не настроен")

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=10)) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.is_error:
                detail = (response.text or "").strip().replace("\n", " ")[:1200]
                raise ProviderError(
                    f"Groq HTTP {response.status_code}: {detail or response.reason_phrase}"
                )
            data = response.json()

        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError("Groq вернул пустой или неподдерживаемый ответ")
        return answer.strip()
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ProviderError(f"Groq не ответил корректно: {exc}") from exc


async def reply(messages, persona):
    system = SYSTEM_PROMPT.format(persona=persona or "стандартный FC Mate")
    answer = await _completion(
        [{"role": "system", "content": system}, *messages],
        temperature=0.85,
        max_tokens=500,
    )
    if answer.strip().upper() == "[SKIP]":
        return ""
    return answer[:4000]


async def summarize(memory, messages):
    if not messages:
        return memory or ""
    prompt = (
        "Сделай краткое обновление долгосрочной памяти этой игровой группы. "
        "Сохраняй только устойчивые, не чувствительные факты: игровые предпочтения, любимые клубы/карты, "
        "общие мемы и важные контексты. Не сохраняй адреса, контакты, здоровье, финансы, личные секреты, "
        "не делай догадок. Русский язык, максимум 1000 символов. Предыдущая память:\n"
        + (memory or "пусто")
        + "\nСвежие сообщения:\n"
        + "\n".join(m["content"] for m in messages[-30:])
    )
    result = await _completion(
        [
            {"role": "system", "content": "Редактор безопасной памяти группового чата."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    return result[:3000]
