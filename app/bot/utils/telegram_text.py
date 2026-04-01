from __future__ import annotations

from collections.abc import Sequence

TELEGRAM_TEXT_LIMIT = 4096
DEFAULT_SAFE_LIMIT = 4000
DEFAULT_LONG_EDIT_NOTICE = "📄 Отчет слишком большой, отправляю частями ниже."



def split_text_for_telegram(text: str, limit: int = DEFAULT_SAFE_LIMIT) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if text == "":
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_at = _find_split_index(remaining, limit)
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    if remaining:
        chunks.append(remaining)
    return chunks



def _find_split_index(text: str, limit: int) -> int:
    search_zone = text[: limit + 1]
    for separator in ("\n\n", "\n", " "):
        idx = search_zone.rfind(separator)
        if idx > 0:
            return min(idx + len(separator), limit)
    return limit


async def send_long_message(message, text: str, *, limit: int = DEFAULT_SAFE_LIMIT, **answer_kwargs) -> Sequence:
    chunks = split_text_for_telegram(text, limit=limit)
    results = []

    first_kwargs = dict(answer_kwargs)
    other_kwargs = dict(answer_kwargs)
    other_kwargs.pop("reply_markup", None)

    for idx, chunk in enumerate(chunks):
        kwargs = first_kwargs if idx == 0 else other_kwargs
        results.append(await message.answer(chunk, **kwargs))

    return results


async def edit_or_send_long_message(
    message,
    text: str,
    *,
    limit: int = DEFAULT_SAFE_LIMIT,
    too_long_notice: str = DEFAULT_LONG_EDIT_NOTICE,
    **edit_kwargs,
):
    if len(text) <= limit:
        return await message.edit_text(text, **edit_kwargs)

    notice_kwargs = dict(edit_kwargs)
    notice_kwargs.pop("reply_markup", None)
    await message.edit_text(too_long_notice, **notice_kwargs)
    return await send_long_message(message, text, limit=limit)
