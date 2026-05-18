import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.utils import broadcast as broadcast_mod
from telethon.errors import FloodWaitError, RPCError, UserIsBlockedError
from telethon.tl.types import Message

FLOOD_SECONDS = 2
EXPECTED_CALLS = [1, 2, 2, 3, 4, 5, 5]


class Sender:
    def __init__(self, effects: dict[int, list[Exception | None]]) -> None:
        self.effects = effects
        self.calls: list[int] = []

    async def __call__(self, chat_id: int, _message: Any) -> None:
        self.calls.append(chat_id)
        effect = self.effects.get(chat_id, [None]).pop(0)
        if effect is not None:
            raise effect


def test_parse_broadcast_filters_active_and_username_only() -> None:
    filters, error = broadcast_mod.parse_broadcast_filters("active_within 3\nusername_only yes")

    assert error is None
    assert filters["username_only"] is True
    assert abs(filters["active_after"] - (datetime.now(UTC) - timedelta(days=3))) < timedelta(
        seconds=5
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", None),
        ("done", None),
        ("active_within nope", 'Invalid number for "active_within".'),
        ("active_within -1", '"active_within" must be positive.'),
        ("username_only no", None),
        ("unknown option", 'Unrecognized filter: "unknown option".'),
    ],
)
def test_parse_broadcast_filters_errors(raw: str, message: str | None) -> None:
    filters, error = broadcast_mod.parse_broadcast_filters(raw)

    if message is None:
        assert error is None
    else:
        assert filters == {}
        assert error == message


def test_extract_filters_text_removes_command_prefix() -> None:
    assert broadcast_mod.extract_filters_text("/broadcast\nactive_within 7") == "active_within 7"
    assert broadcast_mod.extract_filters_text("active_within 7") == "active_within 7"


def test_broadcast_to_chats_retries_flood_and_removes_only_permanent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(broadcast_mod, "sleep", fake_sleep)
    sender = Sender(
        {
            1: [None],
            2: [FloodWaitError(None, FLOOD_SECONDS), None],
            3: [UserIsBlockedError(None)],
            4: [RPCError(None, "TEMPORARY", 500)],
            5: [FloodWaitError(None, FLOOD_SECONDS), UserIsBlockedError(None)],
        }
    )
    removed: list[int] = []
    chats = [
        Chat(user_id=1, user_name="one", type=0),
        Chat(user_id=2, user_name="two", type=0),
        Chat(user_id=3, user_name="three", type=0),
        Chat(user_id=4, user_name="four", type=0),
        Chat(user_id=5, user_name="five", type=0),
    ]

    sent, failed = asyncio.run(
        broadcast_mod.broadcast_to_chats(sender, cast(Message, object()), chats, removed.append)
    )

    assert (sent, failed) == (2, 3)
    assert sender.calls == EXPECTED_CALLS
    assert removed == [3, 5]
    assert slept == [
        broadcast_mod.SLEEP_AFTER_SEND,
        FLOOD_SECONDS + 1,
        broadcast_mod.SLEEP_AFTER_SEND,
        FLOOD_SECONDS + 1,
    ]
