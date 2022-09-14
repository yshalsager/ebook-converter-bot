from asyncio import sleep
from functools import wraps

from telethon import events
from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    InputUserDeactivatedError,
    InterdcCallErrorError,
    MessageIdInvalidError,
    MessageNotModifiedError,
    SlowModeWaitError,
    UserIsBlockedError,
)
from telethon.tl.types import User


def tg_exceptions_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except (
            ChannelPrivateError,
            ChatWriteForbiddenError,
            UserIsBlockedError,
            InterdcCallErrorError,
            MessageNotModifiedError,
            InputUserDeactivatedError,
            MessageIdInvalidError,
        ):
            pass
        except SlowModeWaitError as error:
            await sleep(error.seconds)
            return tg_exceptions_handler(await func(*args, **kwargs))
        except FloodWaitError as error:
            await sleep(error.seconds)
            return tg_exceptions_handler(await func(*args, **kwargs))

    return wrapper


def get_chat_type(event: events.NewMessage.Event) -> int:
    return 0 if event.is_private else 1 if event.is_group else 2


def get_chat_name(event: events.NewMessage.Event) -> str:
    if isinstance(event.chat, User):
        name = ""
        if event.chat.first_name:
            name += event.chat.first_name.strip()
        if event.chat.last_name:
            name += " " + event.chat.last_name.strip()
        return name
    return event.chat.title
