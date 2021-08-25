""" Bot main module"""

from telethon import events

from ebook_converter_bot.bot import BOT


@BOT.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Send a message when the command /start is sent."""
    await event.reply("Hi!")
    raise events.StopPropagation  # Other handlers won't have an event to work with
