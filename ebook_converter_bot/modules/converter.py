"""Converter"""
from telethon import events

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.utils.supported_types import is_supported_input_type


@BOT.on(events.NewMessage(func=lambda x: x.message.file))
async def file_converter(event):
    """Send a message when the command /start is sent."""
    if is_supported_input_type(event.message.file.name):
        await event.reply("Supported type!")
