"""Telegram Bot."""

import asyncio
import json
import logging
from pathlib import Path
from typing import cast

from telethon import TelegramClient
from telethon.tl.types import User

from ebook_converter_bot import API_HASH, API_KEY, BOT_TOKEN
from ebook_converter_bot.db.curd import generate_analytics_columns
from ebook_converter_bot.db.session import initialize_database
from ebook_converter_bot.modules import ALL_MODULES
from ebook_converter_bot.utils.convert import Converter
from ebook_converter_bot.utils.loader import load_modules
from ebook_converter_bot.utils.pdf_fonts import refresh_pdf_font_cache

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

LOGGER = logging.getLogger(__name__)
BOT = TelegramClient("ebook_converter_bot", API_KEY, API_HASH, loop=_loop).start(
    bot_token=BOT_TOKEN
)
BOT.parse_mode = "markdown"
BOT_INFO = {}


def main() -> None:
    """Main."""
    refresh_pdf_font_cache()
    initialize_database()
    generate_analytics_columns(Converter.get_supported_types())
    BOT.loop.run_until_complete(run())


async def run() -> None:
    """Run the bot."""
    bot_info = cast(User, await BOT.get_me())
    BOT_INFO.update({"name": bot_info.first_name, "username": bot_info.username, "id": bot_info.id})
    LOGGER.info(
        "Bot started as %s! Username is %s and ID is %s",
        BOT_INFO["name"],
        BOT_INFO["username"],
        BOT_INFO["id"],
    )
    load_modules(ALL_MODULES, __package__ or "ebook_converter_bot")
    # Check if the bot is restarting
    restart_path = Path("restart.json")
    if restart_path.exists():
        try:
            restart_message = json.loads(restart_path.read_text())
            await BOT.edit_message(
                restart_message["chat"],
                restart_message["message"],
                "Restarted Successfully!",
            )
        except Exception as error:  # noqa: BLE001
            LOGGER.warning(f"Failed to send restart confirmation: {error}")
        finally:
            restart_path.unlink(missing_ok=True)
    async with BOT:
        await BOT.run_until_disconnected()
