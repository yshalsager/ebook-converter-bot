""" Bot restart module"""
import pickle
from os import execl
from sys import executable

from telethon import events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.i18n import translate as _


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"/restart"))
async def restart(event):
    """restart the bot"""
    restart_message = await event.reply(
        _("Restarting, please wait...", get_lang(event.chat_id))
    )
    chat_info = {"chat": restart_message.chat_id, "message": restart_message.id}
    with open(f"restart.pickle", "wb") as out:
        pickle.dump(chat_info, out)
    execl(executable, executable, "-m", "ebook_converter_bot")
