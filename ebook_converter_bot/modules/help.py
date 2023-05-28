"""Bot Help module."""

from telethon import events

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler


@BOT.on(events.NewMessage(pattern="/help"))
@tg_exceptions_handler
async def help_handler(event: events.NewMessage.Event) -> None:
    """Send a message when the command /help is sent."""
    await event.reply(
        _(
            """**Bot Usage:**\n
Forward any supported file to the bot and choose the required format to convert to, and in few seconds the bot will reply you with the converted file.
The bot works in groups too. Reply with /convert to any file then do the same steps as in private.
You can change the preferences of the bot such as language using /settings or /preferences commands.""",
            get_lang(event.chat_id),
        )
    )
