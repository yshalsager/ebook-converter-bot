""" Bot restart module"""
import pickle
from os import execl
from sys import executable

from telethon import events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r'/restart'))
async def restart(event):
    """ restart Samsung bot """
    restart_message = await event.reply("Restarting, please wait...")
    chat_info = {
        'chat': restart_message.chat_id,
        'message': restart_message.id
    }
    with open(f"restart.pickle", "wb") as out:
        pickle.dump(chat_info, out)
    execl(executable, executable, "-m", "ebook_converter_bot")
