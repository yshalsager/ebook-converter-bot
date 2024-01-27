"""Bot stats module."""

from telethon import events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import (
    get_chats_count,
    get_top_formats,
    get_usage_count,
)


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"/stats"))
async def stats(event: events.NewMessage.Event) -> None:
    stats_message = await event.reply("Getting stats, please wait...")
    all_chats, active_chats = get_chats_count()
    usage_times, output_times = get_usage_count()
    output_formats, input_formats = get_top_formats()

    message = (
        f"**Active users**: {active_chats!s}\n"
        f"**All users**: {all_chats!s}\n"
        f"**Total usage count**: {usage_times!s}\n"
        f"**Total successfully converted books**: {output_times!s}\n\n"
        f"**Top output formats**:\n"
        f"$output_formats\n"
        f"**Top input formats**:\n"
        f"$input_formats\n"
    )
    output_formats_message = ""
    for output_format, count in output_formats.items():
        output_formats_message += f"    __{output_format}__: {count!s} times.\n"
    input_formats_message = ""
    for input_format, count in input_formats.items():
        input_formats_message += f"    __{input_format}__: {count!s} times.\n"
    message = message.replace("$output_formats", output_formats_message)
    message = message.replace("$input_formats", input_formats_message)

    await stats_message.edit(message)
