"""Bot broadcast module."""

from telethon import events
from telethon.tl.types import Message

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_broadcast_chats, get_lang, remove_chat
from ebook_converter_bot.utils.broadcast import (
    broadcast_to_chats,
    extract_filters_text,
    filters_help_text,
    parse_broadcast_filters,
)
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler


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
    filters_text = extract_filters_text(event.message.message)
    filters_payload, error = parse_broadcast_filters(filters_text)
    if error:
        await event.reply(f"{error}\n{filters_help_text()}")
        return

    chats = get_broadcast_chats(filters_payload or None)
    if not chats:
        await event.reply(_("No recipients to broadcast to.", lang))
        return

    message_to_send: Message = await event.get_reply_message()
    sent_successfully, failed_to_send = await broadcast_to_chats(
        BOT.send_message,
        message_to_send,
        chats,
        remove_chat,
    )
    broadcast_status_message: str = _(
        "Broadcasting completed! Message was sent to {} chats\n",
        lang,
    ).format(sent_successfully)
    if failed_to_send:
        broadcast_status_message += _(
            "Failed to broadcast to {} chats, most likely because bot has been stopped or kicked out.",
            lang,
        ).format(failed_to_send)
    await event.reply(broadcast_status_message)
