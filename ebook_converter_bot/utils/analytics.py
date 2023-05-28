from collections.abc import Callable
from functools import wraps
from typing import Any

from telethon import events

from ebook_converter_bot.db.curd import increment_usage, update_format_analytics


def analysis(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    async def wrapper(event: events.CallbackQuery.Event) -> Any | None:
        convert_func_results = await func(event)
        if convert_func_results:
            input_type, output_type = convert_func_results
            increment_usage(event.chat_id)
            update_format_analytics(input_type)
            update_format_analytics(output_type, output=True)
            return input_type, output_type
        return None

    return wrapper
