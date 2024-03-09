"""Bot broadcast module."""

import logging
from asyncio import sleep

from telethon import events
from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    UserIsBlockedError,
)
from telethon.tl.types import Message

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_all_chats, get_lang, remove_chat
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler

logger = logging.getLogger(__name__)


@BOT.on(
    events.NewMessage(
        from_users=TG_BOT_ADMINS,
        pattern="/broadcast",
        func=lambda x: x.is_private and x.message.reply_to,
    )
)
@tg_exceptions_handler
async def broadcast_handler(event: events.NewMessage.Event) -> None:
    """Broadcasts message to bot users."""
    lang = get_lang(event.chat_id)
    message_to_send: Message = await event.get_reply_message()
    failed_to_send = 0
    sent_successfully = 0
    chat: Chat
    for chat in get_all_chats():
        try:
            await BOT.send_message(chat.user_id, message_to_send)
            sent_successfully += 1
            await sleep(2)
        except (
            ValueError,
            ChatWriteForbiddenError,
            ChannelPrivateError,
            UserIsBlockedError,
        ) as err:
            failed_to_send += 1
            logger.warning(f"Failed to send message to {chat}:\n{err}")
            remove_chat(chat.user_id)
    broadcast_status_message: str = _(
        f"Broadcasting completed! Message was sent to {sent_successfully} chats\n",
        lang,
    )
    if failed_to_send:
        broadcast_status_message += _(
            f"Failed to broadcast to {failed_to_send} chats, most likely because bot has been stopped or kicked out.",
            lang,
        )
    await event.reply("Broadcast done!")
