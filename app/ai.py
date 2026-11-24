import httpx

from .config import GROQ_API_KEY, GROQ_API_URL, GROQ_MODEL, GROQ_VISION_MODEL
from .persona import SYSTEM_PROMPT


class ProviderError(RuntimeError):
    pass


async def _completion(messages, temperature=0.8, max_tokens=450, model=None):
    if not GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY не настроен в Amvera")
    if not GROQ_API_URL:
        raise ProviderError("GROQ_API_URL не настроен")
    if not GROQ_MODEL:
        raise ProviderError("GROQ_MODEL не настроен")

    payload = {
        "model": model or GROQ_MODEL,
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


async def reply(messages, persona, image_data=None, image_mime='image/jpeg'):
    system = SYSTEM_PROMPT.format(persona=persona or "стандартный FC Mate")
    request_messages = [{"role": "system", "content": system}, *messages]
    model = GROQ_MODEL
    if image_data:
        # Attach the image to the actual latest user turn. Sending it as a
        # separate trailing turn disconnects it from the user's caption/question.
        image_text = (
            "Разбери именно прикреплённый скриншот FC Mobile и ответь на текст этого сообщения. "
            "Если спрашивают OVR, найди цифры именно в поле OVR нужной карточки игрока. "
            "Не подменяй OVR карточки общим OVR состава, рейтингом команды, рангом или другим числом. "
            "Сначала визуально проверь сами цифры. Называй OVR только если все цифры отчётливо видны. "
            "Если цифры мелкие, размыты, закрыты или ты не уверен хотя бы в одной цифре — НЕ угадывай, "
            "не пиши типовое значение вроде 90; прямо скажи, что OVR на этом изображении не удаётся надёжно прочитать, "
            "и попроси крупный фрагмент карточки. Не выводи OVR из силы состава, позиции, имени игрока или памяти. "
            "Для других данных тоже используй только то, что реально видно."
        )
        image_part = {"type": "image_url", "image_url": {"url": "data:" + image_mime + ";base64," + image_data}}
        attached = False
        if request_messages and request_messages[-1].get("role") == "user":
            latest = request_messages[-1]
            previous_text = latest.get("content", "")
            if isinstance(previous_text, str):
                latest["content"] = [
                    {"type": "text", "text": image_text + "\nТекст сообщения игрока: " + previous_text},
                    image_part,
                ]
                attached = True
        if not attached:
            request_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": image_text}, image_part],
            })
        model = GROQ_VISION_MODEL
    answer = await _completion(
        request_messages,
        temperature=0.35 if image_data else 0.85,
        max_tokens=900 if image_data else 500,
        model=model,
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
