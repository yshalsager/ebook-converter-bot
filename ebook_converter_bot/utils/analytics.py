from functools import wraps

from telethon import events

from ebook_converter_bot.db.curd import increment_usage, update_format_analytics


def analysis(func):
    @wraps(func)
    async def wrapper(event: events.CallbackQuery.Event):
        convert_func = await func(event)
        if convert_func:
            input_type, output_type = convert_func
            increment_usage(event.chat_id)
            update_format_analytics(input_type)
            update_format_analytics(output_type, output=True)
            return input_type, output_type

    return wrapper
