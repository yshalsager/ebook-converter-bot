"""Shared broadcast helpers."""

import logging
from asyncio import sleep
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    InputUserDeactivatedError,
    RPCError,
    SlowModeWaitError,
    UserIsBlockedError,
)
from telethon.tl.types import Message

from ebook_converter_bot.db.models.chat import Chat

LOGGER = logging.getLogger(__name__)
SLEEP_AFTER_SEND = 0.035
FILTER_VALUE_PARTS = 2

RemoveChatCallback = Callable[[int], Any]
SendCallback = Callable[[int, Message], Awaitable[Any]]

PERMANENT_SEND_ERRORS = (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    InputUserDeactivatedError,
    UserIsBlockedError,
    ValueError,
)


async def broadcast_to_chats(
    send_message: SendCallback,
    message: Message,
    chats: Iterable[Chat],
    remove_chat: RemoveChatCallback,
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for chat in chats:
        ok = await _send_to_chat(send_message, message, chat)
        if ok:
            sent += 1
            await sleep(SLEEP_AFTER_SEND)
            continue
        failed += 1
        if ok is False:
            remove_chat(chat.user_id)
    return sent, failed


async def _send_to_chat(send_message: SendCallback, message: Message, chat: Chat) -> bool | None:
    try:
        await send_message(chat.user_id, message)
        return True
    except (FloodWaitError, SlowModeWaitError) as err:
        await sleep(err.seconds + 1)
        try:
            await send_message(chat.user_id, message)
            return True
        except PERMANENT_SEND_ERRORS as retry_err:
            LOGGER.warning("Failed to broadcast to %s after retry: %s", chat, retry_err)
            return False
        except RPCError as retry_err:
            LOGGER.warning("Failed to broadcast to %s after retry: %s", chat, retry_err)
            return None
    except PERMANENT_SEND_ERRORS as err:
        LOGGER.warning("Failed to broadcast to %s: %s", chat, err)
        return False
    except RPCError as err:
        LOGGER.warning("Failed to broadcast to %s: %s", chat, err)
        return None


def parse_broadcast_filters(raw: str) -> tuple[dict[str, Any], str | None]:
    text = (raw or "").strip()
    if not text or text.lower() == "done":
        return {}, None

    filters: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        keyword = parts[0].lower()

        if keyword == "active_within" and len(parts) >= FILTER_VALUE_PARTS:
            try:
                days = int(parts[1])
            except ValueError:
                return {}, 'Invalid number for "active_within".'
            if days < 0:
                return {}, '"active_within" must be positive.'
            filters["active_after"] = datetime.now(UTC) - timedelta(days=days)
            continue

        if keyword == "username_only":
            allow = True
            if len(parts) >= FILTER_VALUE_PARTS:
                allow = parts[1].lower() in {"yes", "true", "1"}
            filters["username_only"] = allow
            continue

        return {}, f'Unrecognized filter: "{line}".'

    return filters, None


def extract_filters_text(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("/broadcast"):
        return raw.removeprefix("/broadcast").strip()
    return raw


def filters_help_text() -> str:
    return (
        'Reply with filters (one per line) or "done" to send to everyone:\n'
        "- active_within DAYS\n"
        "- username_only [yes|no]"
    )
