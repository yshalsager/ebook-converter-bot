"""Bot broadcast module."""

import logging

from telethon import events
from telethon.tl.types import Message

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_broadcast_chats, get_lang, mark_chat_unreachable
from ebook_converter_bot.utils.broadcast import (
    broadcast_to_chats,
    extract_filters_text,
    filters_help_text,
    parse_broadcast_filters,
)
from ebook_converter_bot.utils.i18n import translate as _

LOGGER = logging.getLogger(__name__)


# Not wrapped in tg_exceptions_handler: it retries the whole handler on flood waits,
# which would send the broadcast to everyone a second time.
@BOT.on(
    events.NewMessage(
        from_users=TG_BOT_ADMINS,
        pattern="/broadcast",
        func=lambda x: x.is_private and x.message.reply_to,
    )
)
async def broadcast_handler(event: events.NewMessage.Event) -> None:
    """Broadcasts message to bot users."""
    lang = get_lang(event.chat_id)
    filters_text = extract_filters_text(event.message.message)
    filters_payload, error = parse_broadcast_filters(filters_text)
    if error:
        await event.reply(f"{error}\n{filters_help_text()}")
        return
    confirm = filters_payload.pop("confirm", False)

    chats = get_broadcast_chats(filters_payload or None)
    if not chats:
        await event.reply(_("No recipients to broadcast to.", lang))
        return
    if not confirm:
        types = [chat.type for chat in chats]
        await event.reply(
            f"Dry run: would send to {len(chats)} chats "
            f"({types.count(0)} private, {types.count(1)} groups, {types.count(2)} channels).\n"
            "Add a line `confirm` to send.\n\n" + filters_help_text()
        )
        return

    message_to_send: Message = await event.get_reply_message()
    status = await event.reply(f"Broadcasting to {len(chats)} chats...")

    async def on_progress(done: int, sent: int, failed: int, last_id: int) -> None:
        text = (
            f"Broadcasting: {done}/{len(chats)} done, {sent} sent, {failed} failed.\n"
            f"If interrupted, resume with the same filters plus `after_id {last_id}`."
        )
        LOGGER.info(text)
        await status.edit(text)

    sent_successfully, failed_to_send = await broadcast_to_chats(
        BOT.send_message,
        message_to_send,
        chats,
        mark_chat_unreachable,
        on_progress,
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
    LOGGER.info("Broadcast finished: %s sent, %s failed", sent_successfully, failed_to_send)
    await event.reply(broadcast_status_message)
