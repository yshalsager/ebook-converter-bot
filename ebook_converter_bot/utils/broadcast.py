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

from ebook_converter_bot import LANGUAGES
from ebook_converter_bot.db.models.chat import Chat

LOGGER = logging.getLogger(__name__)
SLEEP_AFTER_SEND = 0.035
FILTER_VALUE_PARTS = 2

PROGRESS_EVERY = 100

MarkUnreachableCallback = Callable[[int], Any]
SendCallback = Callable[[int, Message], Awaitable[Any]]
ProgressCallback = Callable[[int, int, int, int], Awaitable[Any]]  # done, sent, failed, last id

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
    mark_unreachable: MarkUnreachableCallback,
    on_progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for done, chat in enumerate(chats, 1):
        ok = await _send_to_chat(send_message, message, chat)
        if ok:
            sent += 1
            await sleep(SLEEP_AFTER_SEND)
        else:
            failed += 1
            if ok is False:
                mark_unreachable(chat.user_id)
        if on_progress and done % PROGRESS_EVERY == 0:
            try:
                await on_progress(done, sent, failed, chat.user_id)
            except Exception:
                LOGGER.warning("Broadcast progress update failed", exc_info=True)
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


def parse_broadcast_filters(raw: str) -> tuple[dict[str, Any], str | None]:  # noqa: C901, PLR0911, PLR0912
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

        if keyword in {"private_only", "confirm"} and len(parts) == 1:
            filters[keyword] = True
            continue

        if keyword == "lang" and len(parts) == FILTER_VALUE_PARTS:
            if parts[1].lower() not in LANGUAGES:
                return {}, f'"lang" must be one of: {", ".join(LANGUAGES)}.'
            filters["lang"] = parts[1].lower()
            continue

        if keyword == "sample_every" and len(parts) == FILTER_VALUE_PARTS:
            try:
                filters["sample_every"] = int(parts[1])
            except ValueError:
                return {}, 'Invalid number for "sample_every".'
            if filters["sample_every"] < 1:
                return {}, '"sample_every" must be at least 1.'
            continue

        if keyword == "after_id" and len(parts) == FILTER_VALUE_PARTS:
            try:
                filters["after_id"] = int(parts[1])
            except ValueError:
                return {}, 'Invalid number for "after_id".'
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
        "Filters, one per line after /broadcast (without confirm it only counts recipients):\n"
        "- active_within DAYS\n"
        "- username_only [yes|no]\n"
        "- private_only (skip groups and channels)\n"
        "- lang ar|en|tr (chats without a language count as en)\n"
        "- sample_every N (every Nth chat, for a test batch)\n"
        "- after_id ID (resume after an interrupted broadcast)\n"
        "- confirm (actually send)"
    )
