"""Command menus: per language for everyone, plus admin commands in admins' own chats."""

import logging

from telethon import functions, types

from ebook_converter_bot import LANGUAGES, TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.i18n import translate as _

LOGGER = logging.getLogger(__name__)

USER_COMMANDS = {
    "start": "Start the bot",
    "convert": "Reply to a file to convert it",
    "settings": "Bot language",
    "buy": "Plans and your balance",
    "donate": "Support the bot",
    "help": "Help",
    "terms": "Purchase terms and support",
}
GROUP_COMMANDS = ("convert", "help")
ADMIN_COMMANDS = {
    "stats": "Bot statistics",
    "broadcast": "Broadcast the replied message",
    "refund": "Refund a payment or revoke a gift",
    "grant": "Give free conversions",
    "restart": "Restart the bot",
    "update": "Update and restart the bot",
}


def menu(lang: str, names: dict[str, str]) -> list[types.BotCommand]:
    return [types.BotCommand(name, _(text, lang)) for name, text in names.items()]


async def set_chat_commands(user_id: int, lang: str) -> None:
    """Menu for one private chat, in the language chosen in the bot, not the app language."""
    commands = USER_COMMANDS | (ADMIN_COMMANDS if user_id in TG_BOT_ADMINS else {})
    try:
        peer = types.BotCommandScopePeer(await BOT.get_input_entity(user_id))
        await BOT(functions.bots.SetBotCommandsRequest(peer, "", menu(lang, commands)))
    except Exception:
        LOGGER.warning("Could not set commands for %s", user_id, exc_info=True)


async def sync_commands() -> None:
    try:
        group = {name: USER_COMMANDS[name] for name in GROUP_COMMANDS}
        for lang in LANGUAGES:
            code = "" if lang == "en" else lang  # English is the fallback for other app languages
            for scope, names in (
                (types.BotCommandScopeDefault(), USER_COMMANDS),
                (types.BotCommandScopeUsers(), USER_COMMANDS),
                (types.BotCommandScopeChats(), group),
            ):
                await BOT(functions.bots.SetBotCommandsRequest(scope, code, menu(lang, names)))
    except Exception:
        LOGGER.exception("Could not set bot commands")
    for admin in TG_BOT_ADMINS:
        await set_chat_commands(admin, get_lang(admin))


commands_task = BOT.loop.create_task(sync_commands())
