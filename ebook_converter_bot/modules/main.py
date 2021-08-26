""" Bot main module"""

from telethon import events

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.utils.i18n import translate as _


@BOT.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Send a message when the command /start is sent."""
    await event.reply(_("Hi!"))
